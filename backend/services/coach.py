"""
Dataset Coach — full dataset QA system.
Analyzes all assets in a project and produces actionable, prioritized recommendations.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.asset import Asset, ReviewState, ShotType
from services.asset_quality import asset_quality_tuple

logger = logging.getLogger(__name__)


class IssueSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IssueCategory(str, Enum):
    QUALITY = "quality"
    DIVERSITY = "diversity"
    CAPTIONS = "captions"
    IDENTITY = "identity"
    COVERAGE = "coverage"
    BALANCE = "balance"


@dataclass
class CoachIssue:
    id: str
    category: IssueCategory
    severity: IssueSeverity
    title: str
    description: str
    affected_count: int
    affected_asset_ids: list[str]
    recommendation: str
    auto_fixable: bool
    fix_action: Optional[str]  # action name if auto-fixable


@dataclass
class CoachReport:
    project_id: str
    analyzed_at: str
    total_assets: int
    approved_assets: int

    shot_type_distribution: dict[str, int]
    head_angle_distribution: dict[str, int]  # front/3quarter/profile
    expression_distribution: dict[str, int]
    background_distribution: dict[str, int]

    avg_composite_score: float
    score_distribution: dict[str, int]  # "0-10%", "10-20%", ...
    low_quality_count: int
    blur_count: int

    exact_duplicate_count: int
    near_duplicate_clusters: int
    redundancy_score: float

    captioned_count: int
    uncaptioned_count: int
    avg_caption_length: float
    trigger_word_coverage: float

    unique_identities: int
    multi_subject_count: int
    face_visibility_score: float

    issues: list[CoachIssue]

    remove_first: list[str]
    recommended_selection: list[str]
    keep_first: list[str]
    next_best: list[str]
    missing_coverage: list[str]
    improvement_actions: list[str]
    selection_target_count: int

    training_readiness_score: float
    training_readiness_grade: str
    training_readiness_summary: str
    estimated_training_quality: str


class DatasetCoach:

    async def analyze(
        self,
        project_id: str,
        db: AsyncSession,
        trigger_words: list[str] | None = None,
    ) -> CoachReport:
        # Load all assets
        result = await db.execute(
            select(Asset).where(Asset.project_id == project_id)
        )
        assets = result.scalars().all()

        # Load active captions
        from models.caption import CaptionVersion
        if assets:
            caption_result = await db.execute(
                select(CaptionVersion).where(
                    CaptionVersion.asset_id.in_([a.id for a in assets]),
                    CaptionVersion.is_active == True,
                )
            )
            captions_by_asset: dict[str, CaptionVersion] = {
                cv.asset_id: cv for cv in caption_result.scalars().all()
            }
        else:
            captions_by_asset = {}

        total = len(assets)
        analyzed_at = datetime.now(timezone.utc).isoformat()

        if total == 0:
            return CoachReport(
                project_id=project_id,
                analyzed_at=analyzed_at,
                total_assets=0,
                approved_assets=0,
                shot_type_distribution={},
                head_angle_distribution={"front": 0, "3quarter": 0, "profile": 0},
                expression_distribution={},
                background_distribution={},
                avg_composite_score=0.0,
                score_distribution={},
                low_quality_count=0,
                blur_count=0,
                exact_duplicate_count=0,
                near_duplicate_clusters=0,
                redundancy_score=0.0,
                captioned_count=0,
                uncaptioned_count=0,
                avg_caption_length=0.0,
                trigger_word_coverage=0.0,
                unique_identities=0,
                multi_subject_count=0,
                face_visibility_score=0.0,
                issues=[],
                remove_first=[],
                recommended_selection=[],
                keep_first=[],
                next_best=[],
                missing_coverage=["No assets in dataset"],
                improvement_actions=["Add images to the project"],
                selection_target_count=0,
                training_readiness_score=0.0,
                training_readiness_grade="F",
                training_readiness_summary="Dataset is empty.",
                estimated_training_quality="none",
            )

        # ── Shot type distribution ─────────────────────────────────────────────
        shot_type_distribution: dict[str, int] = {}
        for a in assets:
            st = a.shot_type or "unknown"
            shot_type_distribution[st] = shot_type_distribution.get(st, 0) + 1

        # ── Head angle distribution ────────────────────────────────────────────
        head_angle_distribution: dict[str, int] = {"front": 0, "3quarter": 0, "profile": 0, "unknown": 0}
        for a in assets:
            if a.head_pose_yaw is not None:
                yaw = abs(a.head_pose_yaw)
                if yaw < 15:
                    head_angle_distribution["front"] += 1
                elif yaw <= 45:
                    head_angle_distribution["3quarter"] += 1
                else:
                    head_angle_distribution["profile"] += 1
            else:
                head_angle_distribution["unknown"] += 1

        # ── Expression distribution ────────────────────────────────────────────
        expression_distribution: dict[str, int] = {}
        for a in assets:
            if a.face_count and a.face_count > 0:
                expr = a.dominant_emotion or "unknown"
                expression_distribution[expr] = expression_distribution.get(expr, 0) + 1

        # ── Background distribution ────────────────────────────────────────────
        background_distribution: dict[str, int] = {}
        for a in assets:
            if a.is_indoor is not None:
                key = "indoor" if a.is_indoor else "outdoor"
            elif a.scene_class:
                key = a.scene_class
            else:
                key = "unknown"
            background_distribution[key] = background_distribution.get(key, 0) + 1

        # ── Score distribution ─────────────────────────────────────────────────
        score_buckets = {
            "0-10%": 0, "10-20%": 0, "20-30%": 0, "30-40%": 0,
            "40-50%": 0, "50-60%": 0, "60-70%": 0, "70-80%": 0,
            "80-90%": 0, "90-100%": 0,
        }
        for a in assets:
            s = (a.composite_score or 0.0) * 100
            idx = min(int(s / 10), 9)
            keys = list(score_buckets.keys())
            score_buckets[keys[idx]] += 1

        scored = [a for a in assets if a.composite_score is not None]
        avg_composite = sum(a.composite_score for a in scored) / max(len(scored), 1)
        low_quality_count = sum(1 for a in assets if (a.composite_score or 0.0) < 0.4)
        blur_count = sum(1 for a in assets if (a.composite_score or 0.0) < 0.3)

        # ── Duplicate counts ───────────────────────────────────────────────────
        sha_groups: dict[str, list[str]] = {}
        for a in assets:
            if a.sha256_hash:
                sha_groups.setdefault(a.sha256_hash, []).append(a.id)
        exact_duplicate_count = sum(len(v) - 1 for v in sha_groups.values() if len(v) > 1)

        dup_clusters: set[str] = set()
        for a in assets:
            if a.duplicate_cluster_id:
                dup_clusters.add(a.duplicate_cluster_id)
        near_duplicate_clusters = len(dup_clusters)

        assets_with_dup = sum(1 for a in assets if a.duplicate_cluster_id)
        redundancy_score = assets_with_dup / total if total > 0 else 0.0

        # ── Caption metrics ────────────────────────────────────────────────────
        captioned_count = sum(1 for a in assets if a.id in captions_by_asset)
        uncaptioned_count = total - captioned_count

        caption_lengths = [
            len(captions_by_asset[a.id].text)
            for a in assets
            if a.id in captions_by_asset and captions_by_asset[a.id].text
        ]
        avg_caption_length = sum(caption_lengths) / max(len(caption_lengths), 1)

        trigger_word_coverage = 0.0
        if trigger_words and captioned_count > 0:
            tw_hits = 0
            for a in assets:
                cv = captions_by_asset.get(a.id)
                if cv and cv.text:
                    if any(tw.lower() in cv.text.lower() for tw in trigger_words):
                        tw_hits += 1
            trigger_word_coverage = tw_hits / captioned_count

        # ── Identity metrics ───────────────────────────────────────────────────
        identity_clusters: set[str] = set()
        for a in assets:
            if a.identity_cluster_id:
                identity_clusters.add(a.identity_cluster_id)
        unique_identities = max(len(identity_clusters), 1)

        multi_subject_count = sum(1 for a in assets if (a.face_count or 0) > 1)

        face_assets = [a for a in assets if (a.face_count or 0) > 0 and a.face_quality is not None]
        face_visibility_score = (
            sum(a.face_quality for a in face_assets) / len(face_assets)
            if face_assets else 0.0
        )

        # ── Approved count ─────────────────────────────────────────────────────
        approved_assets = sum(1 for a in assets if a.review_state == ReviewState.APPROVED.value)

        # ── Run all checks ─────────────────────────────────────────────────────
        issues: list[CoachIssue] = []
        issues.extend(self._check_dataset_size(assets))
        issues.extend(self._check_quality_floor(assets))
        issues.extend(self._check_duplicate_ratio(assets))
        issues.extend(self._check_shot_type_diversity(assets))
        issues.extend(self._check_expression_diversity(assets))
        issues.extend(self._check_angle_diversity(assets))
        issues.extend(self._check_background_diversity(assets))
        issues.extend(self._check_caption_quality(assets, trigger_words, captions_by_asset))
        issues.extend(self._check_identity_contamination(assets))

        # ── Compute readiness ──────────────────────────────────────────────────
        readiness_score, readiness_grade, readiness_summary = self._compute_training_readiness(issues, assets)

        quality_label_map = [
            (90, "excellent"),
            (80, "good"),
            (70, "adequate"),
            (60, "poor"),
            (0, "insufficient"),
        ]
        estimated_quality = "insufficient"
        for threshold, label in quality_label_map:
            if readiness_score >= threshold:
                estimated_quality = label
                break

        # recommended_selection — quality-sorted so the caller gets a clean
        # score-ranked list of all images worth including in training.
        eligible = [a for a in assets if not a.is_rejected]
        selection_target_count = self._recommended_selection_target(total)
        quality_sorted = sorted(eligible, key=lambda a: asset_quality_tuple(a), reverse=True)
        recommended_selection = [a.id for a in quality_sorted[:selection_target_count]]

        # keep_first — diversity-greedy ordering of the recommended set so the
        # user sees the most varied, highest-value images first.
        diversity_ordered = self._rank_training_candidates(quality_sorted[:selection_target_count])
        next_best = [
            a.id for a in quality_sorted[selection_target_count:selection_target_count + 10]
        ]

        return CoachReport(
            project_id=project_id,
            analyzed_at=analyzed_at,
            total_assets=total,
            approved_assets=approved_assets,
            shot_type_distribution=shot_type_distribution,
            head_angle_distribution=head_angle_distribution,
            expression_distribution=expression_distribution,
            background_distribution=background_distribution,
            avg_composite_score=round(avg_composite, 3),
            score_distribution=score_buckets,
            low_quality_count=low_quality_count,
            blur_count=blur_count,
            exact_duplicate_count=exact_duplicate_count,
            near_duplicate_clusters=near_duplicate_clusters,
            redundancy_score=round(redundancy_score, 3),
            captioned_count=captioned_count,
            uncaptioned_count=uncaptioned_count,
            avg_caption_length=round(avg_caption_length, 1),
            trigger_word_coverage=round(trigger_word_coverage, 3),
            unique_identities=unique_identities,
            multi_subject_count=multi_subject_count,
            face_visibility_score=round(face_visibility_score, 3),
            issues=issues,
            remove_first=self._select_remove_first(assets, issues),
            recommended_selection=recommended_selection,
            keep_first=diversity_ordered[:10],
            next_best=next_best,
            missing_coverage=self._compute_missing_coverage(assets),
            improvement_actions=self._compute_improvement_actions(issues),
            selection_target_count=selection_target_count,
            training_readiness_score=round(readiness_score, 1),
            training_readiness_grade=readiness_grade,
            training_readiness_summary=readiness_summary,
            estimated_training_quality=estimated_quality,
        )

    def _check_shot_type_diversity(self, assets: list[Asset]) -> list[CoachIssue]:
        issues: list[CoachIssue] = []
        if not assets:
            return issues

        total = len(assets)
        shot_counts: dict[str, int] = {}
        for a in assets:
            st = a.shot_type or "unknown"
            shot_counts[st] = shot_counts.get(st, 0) + 1

        # All same shot type
        non_unknown = {k: v for k, v in shot_counts.items() if k != "unknown"}
        if len(non_unknown) == 1:
            single_type = list(non_unknown.keys())[0]
            affected = [a.id for a in assets if (a.shot_type or "unknown") == single_type]
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.DIVERSITY,
                severity=IssueSeverity.HIGH,
                title="All images are the same shot type",
                description=f"Every image is '{single_type}'. Models trained on a single shot type generalize poorly.",
                affected_count=len(affected),
                affected_asset_ids=affected[:50],
                recommendation="Add images with different shot types (wide, medium, closeup, full body).",
                auto_fixable=False,
                fix_action=None,
            ))
            return issues

        # >70% closeups
        closeup_count = shot_counts.get("closeup", 0) + shot_counts.get("extreme_closeup", 0)
        if total > 0 and closeup_count / total > 0.70:
            affected = [a.id for a in assets if a.shot_type in ("closeup", "extreme_closeup")]
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.BALANCE,
                severity=IssueSeverity.HIGH,
                title="Too many closeup shots",
                description=f"{closeup_count}/{total} ({closeup_count/total:.0%}) are closeups. Model will struggle to generate non-closeup images.",
                affected_count=closeup_count,
                affected_asset_ids=affected[:50],
                recommendation="Add wide, medium, and full-body shots to balance the dataset.",
                auto_fixable=False,
                fix_action=None,
            ))

        # No wide/full_body
        has_wide = shot_counts.get("wide", 0) + shot_counts.get("full_body", 0) > 0
        if not has_wide:
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.COVERAGE,
                severity=IssueSeverity.MEDIUM,
                title="No wide or full-body shots",
                description="Dataset lacks wide and full-body shots, limiting body/outfit generation.",
                affected_count=total,
                affected_asset_ids=[],
                recommendation="Add at least 3-5 full-body or wide shots showing full outfit and pose.",
                auto_fixable=False,
                fix_action=None,
            ))

        return issues

    def _check_expression_diversity(self, assets: list[Asset]) -> list[CoachIssue]:
        issues: list[CoachIssue] = []
        face_assets = [a for a in assets if (a.face_count or 0) > 0]
        if not face_assets:
            return issues

        total_faces = len(face_assets)
        emotion_counts: dict[str, int] = {}
        for a in face_assets:
            expr = a.dominant_emotion or "neutral"
            emotion_counts[expr] = emotion_counts.get(expr, 0) + 1

        # All neutral
        neutral_count = emotion_counts.get("neutral", 0)
        if neutral_count == total_faces:
            affected = [a.id for a in face_assets if (a.dominant_emotion or "neutral") == "neutral"]
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.DIVERSITY,
                severity=IssueSeverity.HIGH,
                title="All expressions are neutral",
                description="Every image shows a neutral expression. Model will struggle to generate other expressions.",
                affected_count=neutral_count,
                affected_asset_ids=affected[:50],
                recommendation="Add images with varied expressions: smiling, laughing, serious, surprised.",
                auto_fixable=False,
                fix_action=None,
            ))
            return issues

        # No smile
        smile_count = emotion_counts.get("happy", 0) + emotion_counts.get("smile", 0)
        if smile_count == 0:
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.COVERAGE,
                severity=IssueSeverity.MEDIUM,
                title="No smiling/happy expressions",
                description="Dataset has no happy or smiling expressions. Add some for better expression coverage.",
                affected_count=total_faces,
                affected_asset_ids=[],
                recommendation="Include 3-5 images with natural smiling expressions.",
                auto_fixable=False,
                fix_action=None,
            ))

        # >60% same expression
        if emotion_counts:
            dominant_expr = max(emotion_counts, key=lambda k: emotion_counts[k])
            dominant_count = emotion_counts[dominant_expr]
            if total_faces > 0 and dominant_count / total_faces > 0.60:
                affected = [a.id for a in face_assets if (a.dominant_emotion or "neutral") == dominant_expr]
                issues.append(CoachIssue(
                    id=str(uuid.uuid4()),
                    category=IssueCategory.BALANCE,
                    severity=IssueSeverity.HIGH,
                    title=f"Expression imbalance: '{dominant_expr}' dominates",
                    description=f"{dominant_count}/{total_faces} ({dominant_count/total_faces:.0%}) show '{dominant_expr}' expression.",
                    affected_count=dominant_count,
                    affected_asset_ids=affected[:50],
                    recommendation="Diversify expressions to improve model generalization.",
                    auto_fixable=False,
                    fix_action=None,
                ))

        return issues

    def _check_angle_diversity(self, assets: list[Asset]) -> list[CoachIssue]:
        issues: list[CoachIssue] = []
        yaw_assets = [a for a in assets if a.head_pose_yaw is not None]
        if not yaw_assets:
            return issues

        front = [a for a in yaw_assets if abs(a.head_pose_yaw) < 15]
        quarter = [a for a in yaw_assets if 15 <= abs(a.head_pose_yaw) <= 45]
        profile = [a for a in yaw_assets if abs(a.head_pose_yaw) > 45]

        total_yaw = len(yaw_assets)

        # All front-facing
        if len(front) == total_yaw and total_yaw > 0:
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.DIVERSITY,
                severity=IssueSeverity.HIGH,
                title="All images are front-facing",
                description="Every image has a direct front-facing angle. Model will not learn other angles.",
                affected_count=total_yaw,
                affected_asset_ids=[a.id for a in front[:50]],
                recommendation="Add 3/4 and profile angles for better angular coverage.",
                auto_fixable=False,
                fix_action=None,
            ))
            return issues

        # No profile views
        if len(profile) == 0:
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.COVERAGE,
                severity=IssueSeverity.MEDIUM,
                title="No profile (side) views",
                description="Dataset has no side-profile angle images.",
                affected_count=total_yaw,
                affected_asset_ids=[],
                recommendation="Add 2-4 profile/side-facing images for better angle coverage.",
                auto_fixable=False,
                fix_action=None,
            ))

        # No 3/4 views
        if len(quarter) == 0:
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.COVERAGE,
                severity=IssueSeverity.MEDIUM,
                title="No three-quarter angle views",
                description="Dataset lacks 3/4 angle images (15–45° yaw).",
                affected_count=total_yaw,
                affected_asset_ids=[],
                recommendation="Add 3-5 three-quarter angle images.",
                auto_fixable=False,
                fix_action=None,
            ))

        return issues

    def _check_background_diversity(self, assets: list[Asset]) -> list[CoachIssue]:
        issues: list[CoachIssue] = []
        # Only check if we have scene data
        scene_assets = [a for a in assets if a.is_indoor is not None or a.scene_class is not None]
        if not scene_assets:
            return issues

        bg_counts: dict[str, int] = {}
        for a in scene_assets:
            if a.is_indoor is not None:
                key = "indoor" if a.is_indoor else "outdoor"
            elif a.scene_class:
                key = a.scene_class
            else:
                key = "unknown"
            bg_counts[key] = bg_counts.get(key, 0) + 1

        if len(bg_counts) == 1:
            sole_bg = list(bg_counts.keys())[0]
            affected = [a.id for a in scene_assets]
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.DIVERSITY,
                severity=IssueSeverity.HIGH,
                title=f"All images have the same background type: '{sole_bg}'",
                description=f"Every image with background data is '{sole_bg}'. Model may overfit to this environment.",
                affected_count=len(affected),
                affected_asset_ids=affected[:50],
                recommendation="Add images from varied environments (indoor, outdoor, studio, etc.).",
                auto_fixable=False,
                fix_action=None,
            ))

        return issues

    def _check_quality_floor(self, assets: list[Asset]) -> list[CoachIssue]:
        issues: list[CoachIssue] = []
        if not assets:
            return issues

        total = len(assets)

        # Any score == 0.0 (unscored or completely failed)
        zero_score = [a for a in assets if a.composite_score is not None and a.composite_score == 0.0]
        if zero_score:
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.QUALITY,
                severity=IssueSeverity.CRITICAL,
                title="Images with zero quality score detected",
                description=f"{len(zero_score)} image(s) have a composite score of 0.0, indicating corrupt or unprocessable files.",
                affected_count=len(zero_score),
                affected_asset_ids=[a.id for a in zero_score[:50]],
                recommendation="Remove or re-analyze these images.",
                auto_fixable=True,
                fix_action="remove_low_quality",
            ))

        # >20% below 0.4
        below_04 = [a for a in assets if (a.composite_score or 0.0) < 0.4]
        pct = len(below_04) / total if total > 0 else 0
        if pct > 0.20:
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.QUALITY,
                severity=IssueSeverity.CRITICAL,
                title="Large proportion of low-quality images",
                description=f"{len(below_04)}/{total} ({pct:.0%}) images score below 0.4. This will significantly hurt training.",
                affected_count=len(below_04),
                affected_asset_ids=[a.id for a in below_04[:50]],
                recommendation="Remove or replace low-quality images (blurry, dark, noisy).",
                auto_fixable=True,
                fix_action="remove_low_quality",
            ))
        elif pct > 0.05:
            # >5% with composite_score < 0.3 (blur proxy)
            blur_proxy = [a for a in assets if (a.composite_score or 0.0) < 0.3]
            if len(blur_proxy) / total > 0.05:
                issues.append(CoachIssue(
                    id=str(uuid.uuid4()),
                    category=IssueCategory.QUALITY,
                    severity=IssueSeverity.HIGH,
                    title="Several very low-quality / blurry images",
                    description=f"{len(blur_proxy)} images score below 0.3, likely blurry or very poor quality.",
                    affected_count=len(blur_proxy),
                    affected_asset_ids=[a.id for a in blur_proxy[:50]],
                    recommendation="Review and remove these images.",
                    auto_fixable=True,
                    fix_action="remove_low_quality",
                ))

        # Average quality < 0.5
        scored = [a for a in assets if a.composite_score is not None]
        if scored:
            avg = sum(a.composite_score for a in scored) / len(scored)
            if avg < 0.5:
                issues.append(CoachIssue(
                    id=str(uuid.uuid4()),
                    category=IssueCategory.QUALITY,
                    severity=IssueSeverity.HIGH,
                    title="Below-average overall quality",
                    description=f"Average composite score is {avg:.2f}. Aim for at least 0.5 for good training results.",
                    affected_count=total,
                    affected_asset_ids=[],
                    recommendation="Improve dataset quality by removing low-scoring images and adding better ones.",
                    auto_fixable=False,
                    fix_action=None,
                ))

        return issues

    def _check_duplicate_ratio(self, assets: list[Asset]) -> list[CoachIssue]:
        issues: list[CoachIssue] = []
        if not assets:
            return issues

        total = len(assets)

        # Exact duplicates
        sha_groups: dict[str, list[str]] = {}
        for a in assets:
            if a.sha256_hash:
                sha_groups.setdefault(a.sha256_hash, []).append(a.id)
        exact_dups = [aid for ids in sha_groups.values() if len(ids) > 1 for aid in ids[1:]]
        if exact_dups:
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.QUALITY,
                severity=IssueSeverity.HIGH,
                title="Exact duplicate images detected",
                description=f"{len(exact_dups)} exact duplicates found (same SHA256 hash). These waste training budget.",
                affected_count=len(exact_dups),
                affected_asset_ids=exact_dups[:50],
                recommendation="Remove exact duplicates, keeping the best copy of each.",
                auto_fixable=True,
                fix_action="remove_exact_duplicates",
            ))

        # >30% with duplicate_cluster_id
        dup_cluster_assets = [a for a in assets if a.duplicate_cluster_id]
        dup_pct = len(dup_cluster_assets) / total if total > 0 else 0
        if dup_pct > 0.30:
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.QUALITY,
                severity=IssueSeverity.CRITICAL,
                title="High near-duplicate ratio",
                description=f"{len(dup_cluster_assets)}/{total} ({dup_pct:.0%}) images are in near-duplicate clusters. Dataset lacks diversity.",
                affected_count=len(dup_cluster_assets),
                affected_asset_ids=[a.id for a in dup_cluster_assets[:50]],
                recommendation="Run duplicate removal to keep only the best image per cluster.",
                auto_fixable=True,
                fix_action="remove_exact_duplicates",
            ))
        elif dup_pct > 0.15:
            # Redundancy score > 0.7 proxy
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.QUALITY,
                severity=IssueSeverity.HIGH,
                title="Moderate near-duplicate ratio",
                description=f"{len(dup_cluster_assets)}/{total} ({dup_pct:.0%}) images are near-duplicates.",
                affected_count=len(dup_cluster_assets),
                affected_asset_ids=[a.id for a in dup_cluster_assets[:50]],
                recommendation="Consider removing near-duplicates to improve dataset variety.",
                auto_fixable=True,
                fix_action="remove_exact_duplicates",
            ))

        return issues

    def _check_caption_quality(
        self,
        assets: list[Asset],
        trigger_words: list[str] | None,
        captions_by_asset: dict[str, Any],
    ) -> list[CoachIssue]:
        issues: list[CoachIssue] = []
        if not assets:
            return issues

        total = len(assets)
        uncaptioned = [a for a in assets if a.id not in captions_by_asset]
        uncaptioned_pct = len(uncaptioned) / total if total > 0 else 0

        # >20% uncaptioned
        if uncaptioned_pct > 0.20:
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.CAPTIONS,
                severity=IssueSeverity.HIGH,
                title="Many images lack captions",
                description=f"{len(uncaptioned)}/{total} ({uncaptioned_pct:.0%}) images have no caption. Uncaptioned images hurt training.",
                affected_count=len(uncaptioned),
                affected_asset_ids=[a.id for a in uncaptioned[:50]],
                recommendation="Generate captions for all images using the bulk captioning tool.",
                auto_fixable=False,
                fix_action=None,
            ))

        # Trigger word missing
        if trigger_words:
            captioned = [a for a in assets if a.id in captions_by_asset]
            if captioned:
                missing_tw = [
                    a for a in captioned
                    if not any(
                        tw.lower() in (captions_by_asset[a.id].text or "").lower()
                        for tw in trigger_words
                    )
                ]
                if missing_tw:
                    issues.append(CoachIssue(
                        id=str(uuid.uuid4()),
                        category=IssueCategory.CAPTIONS,
                        severity=IssueSeverity.HIGH,
                        title="Trigger word missing from captions",
                        description=f"{len(missing_tw)} captions do not contain the trigger word(s): {', '.join(trigger_words)}.",
                        affected_count=len(missing_tw),
                        affected_asset_ids=[a.id for a in missing_tw[:50]],
                        recommendation="Regenerate or edit captions to include the trigger word.",
                        auto_fixable=True,
                        fix_action="normalize_captions",
                    ))

        # Very short average caption
        caption_texts = [captions_by_asset[a.id].text for a in assets if a.id in captions_by_asset and captions_by_asset[a.id].text]
        if caption_texts:
            avg_len = sum(len(t) for t in caption_texts) / len(caption_texts)
            if avg_len < 30:
                issues.append(CoachIssue(
                    id=str(uuid.uuid4()),
                    category=IssueCategory.CAPTIONS,
                    severity=IssueSeverity.MEDIUM,
                    title="Captions are very short",
                    description=f"Average caption length is {avg_len:.0f} characters. Short captions provide insufficient training signal.",
                    affected_count=len(caption_texts),
                    affected_asset_ids=[],
                    recommendation="Use a more detailed captioning style (e.g., 'natural' or 'training_literal').",
                    auto_fixable=False,
                    fix_action=None,
                ))

        return issues

    def _check_identity_contamination(self, assets: list[Asset]) -> list[CoachIssue]:
        issues: list[CoachIssue] = []
        if not assets:
            return issues

        total = len(assets)

        # >15% multi-subject
        multi_subject = [a for a in assets if (a.face_count or 0) > 1]
        pct = len(multi_subject) / total if total > 0 else 0
        if pct > 0.15:
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.IDENTITY,
                severity=IssueSeverity.HIGH,
                title="Too many multi-subject images",
                description=f"{len(multi_subject)}/{total} ({pct:.0%}) images contain multiple faces. This causes identity confusion.",
                affected_count=len(multi_subject),
                affected_asset_ids=[a.id for a in multi_subject[:50]],
                recommendation="Remove images with multiple faces to prevent identity contamination.",
                auto_fixable=False,
                fix_action=None,
            ))

        # Low avg face_quality
        face_scored = [a for a in assets if a.face_quality is not None and (a.face_count or 0) > 0]
        if face_scored:
            avg_fq = sum(a.face_quality for a in face_scored) / len(face_scored)
            if avg_fq < 0.4:
                issues.append(CoachIssue(
                    id=str(uuid.uuid4()),
                    category=IssueCategory.QUALITY,
                    severity=IssueSeverity.HIGH,
                    title="Low average face quality",
                    description=f"Average face quality score is {avg_fq:.2f}. Poor face quality leads to inconsistent identity training.",
                    affected_count=len(face_scored),
                    affected_asset_ids=[],
                    recommendation="Remove images with low face quality, blur, occlusion, or extreme angles.",
                    auto_fixable=False,
                    fix_action=None,
                ))

        return issues

    def _check_dataset_size(self, assets: list[Asset]) -> list[CoachIssue]:
        issues: list[CoachIssue] = []
        total = len(assets)

        if total < 15:
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.COVERAGE,
                severity=IssueSeverity.CRITICAL,
                title="Dataset is too small",
                description=f"Only {total} images. Minimum recommended for LoRA training is 15-20 images.",
                affected_count=total,
                affected_asset_ids=[a.id for a in assets],
                recommendation="Add more images. Aim for at least 30-50 diverse images.",
                auto_fixable=False,
                fix_action=None,
            ))
        elif total < 30:
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.COVERAGE,
                severity=IssueSeverity.HIGH,
                title="Dataset is small",
                description=f"Only {total} images. Recommended minimum for good results is 30+ images.",
                affected_count=total,
                affected_asset_ids=[],
                recommendation="Add more diverse images for better model generalization.",
                auto_fixable=False,
                fix_action=None,
            ))
        elif total < 50:
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.COVERAGE,
                severity=IssueSeverity.MEDIUM,
                title="Dataset could be larger",
                description=f"{total} images. Adding more variety will improve results.",
                affected_count=total,
                affected_asset_ids=[],
                recommendation="Consider adding more images, especially for underrepresented shot types or angles.",
                auto_fixable=False,
                fix_action=None,
            ))
        elif total > 1000:
            issues.append(CoachIssue(
                id=str(uuid.uuid4()),
                category=IssueCategory.BALANCE,
                severity=IssueSeverity.LOW,
                title="Very large dataset",
                description=f"{total} images is quite large for LoRA training. Quality over quantity is important.",
                affected_count=total,
                affected_asset_ids=[],
                recommendation="Consider curating the dataset to keep only the highest-quality images.",
                auto_fixable=False,
                fix_action=None,
            ))

        return issues

    def _compute_training_readiness(
        self,
        issues: list[CoachIssue],
        assets: list[Asset],
    ) -> tuple[float, str, str]:
        score = 100.0

        severity_penalties = {
            IssueSeverity.CRITICAL: 25.0,
            IssueSeverity.HIGH: 10.0,
            IssueSeverity.MEDIUM: 5.0,
            IssueSeverity.LOW: 1.0,
        }

        for issue in issues:
            score -= severity_penalties.get(issue.severity, 0)

        score = max(0.0, score)

        if score >= 90:
            grade = "A"
            summary = "Dataset is in excellent shape and ready for training."
        elif score >= 80:
            grade = "B"
            summary = "Dataset is good with minor issues to address."
        elif score >= 70:
            grade = "C"
            summary = "Dataset is acceptable but has several issues that may affect quality."
        elif score >= 60:
            grade = "D"
            summary = "Dataset has significant problems. Address critical and high-severity issues before training."
        else:
            grade = "F"
            summary = "Dataset is not ready for training. Multiple critical issues must be resolved first."

        return score, grade, summary

    def _select_remove_first(self, assets: list[Asset], issues: list[CoachIssue]) -> list[str]:
        # Worst by composite_score + has duplicate_cluster_id
        dup_ids: set[str] = {
            aid
            for issue in issues
            for aid in issue.affected_asset_ids
            if issue.fix_action == "remove_exact_duplicates"
        }

        def _sort_key(a: Asset) -> float:
            score = a.composite_score or 0.0
            # Penalize duplicates
            if a.duplicate_cluster_id or a.id in dup_ids:
                score -= 0.5
            return score

        sorted_assets = sorted(assets, key=_sort_key)
        return [a.id for a in sorted_assets[:10]]

    def _recommended_selection_target(self, total_assets: int) -> int:
        if total_assets <= 0:
            return 0
        if total_assets < 20:
            return total_assets
        if total_assets < 40:
            return min(total_assets, 30)
        return min(total_assets, 50)

    def _rank_training_candidates(self, assets: list[Asset]) -> list[str]:
        eligible = [a for a in assets if not a.is_rejected]
        if not eligible:
            return []

        shot_counts: dict[str, int] = {}
        angle_counts: dict[str, int] = {}
        expr_counts: dict[str, int] = {}
        bg_counts: dict[str, int] = {}
        for asset in eligible:
            shot_counts[self._shot_bucket(asset)] = shot_counts.get(self._shot_bucket(asset), 0) + 1
            angle_counts[self._angle_bucket(asset)] = angle_counts.get(self._angle_bucket(asset), 0) + 1
            expr_counts[self._expression_bucket(asset)] = expr_counts.get(self._expression_bucket(asset), 0) + 1
            bg_counts[self._background_bucket(asset)] = bg_counts.get(self._background_bucket(asset), 0) + 1

        selected: list[Asset] = []
        remaining = eligible[:]

        while remaining:
            chosen = max(
                remaining,
                key=lambda asset: (
                    self._selection_score(
                        asset,
                        selected=selected,
                        shot_counts=shot_counts,
                        angle_counts=angle_counts,
                        expr_counts=expr_counts,
                        bg_counts=bg_counts,
                    ),
                    asset.id,
                ),
            )
            selected.append(chosen)
            remaining = [asset for asset in remaining if asset.id != chosen.id]

        return [asset.id for asset in selected]

    def _selection_score(
        self,
        asset: Asset,
        *,
        selected: list[Asset],
        shot_counts: dict[str, int],
        angle_counts: dict[str, int],
        expr_counts: dict[str, int],
        bg_counts: dict[str, int],
    ) -> float:
        quality = asset_quality_tuple(asset)
        base_score = (
            quality[0] * 4.0
            + quality[1] * 3.0
            + quality[2] * 2.0
            + quality[3] * 1.5
            + quality[4] * 1.0
            + quality[5] * 1.0
            + quality[6] * 1.5
            + min(quality[7] / 1_000_000.0, 4.0) * 0.1
        )

        if asset.review_state == ReviewState.APPROVED.value:
            base_score += 0.4
        elif asset.review_state == ReviewState.PENDING.value:
            base_score += 0.1

        if asset.face_count == 1:
            base_score += 0.25
        elif (asset.face_count or 0) > 1:
            base_score -= 1.5

        if asset.duplicate_cluster_id:
            base_score -= 1.25
        if asset.is_flagged:
            base_score -= 0.75

        selected_shots = {self._shot_bucket(item) for item in selected}
        selected_angles = {self._angle_bucket(item) for item in selected}
        selected_exprs = {self._expression_bucket(item) for item in selected}
        selected_backgrounds = {self._background_bucket(item) for item in selected}

        shot_bucket = self._shot_bucket(asset)
        angle_bucket = self._angle_bucket(asset)
        expr_bucket = self._expression_bucket(asset)
        bg_bucket = self._background_bucket(asset)

        coverage_bonus = 0.0
        if shot_bucket not in selected_shots:
            coverage_bonus += 0.8
        coverage_bonus += 0.25 / max(shot_counts.get(shot_bucket, 1), 1)

        if angle_bucket not in selected_angles:
            coverage_bonus += 0.55
        coverage_bonus += 0.2 / max(angle_counts.get(angle_bucket, 1), 1)

        if expr_bucket not in selected_exprs and expr_bucket != "unknown":
            coverage_bonus += 0.4
        coverage_bonus += 0.15 / max(expr_counts.get(expr_bucket, 1), 1)

        if bg_bucket not in selected_backgrounds and bg_bucket != "unknown":
            coverage_bonus += 0.3
        coverage_bonus += 0.1 / max(bg_counts.get(bg_bucket, 1), 1)

        return base_score + coverage_bonus

    def _shot_bucket(self, asset: Asset) -> str:
        return asset.shot_type or ShotType.UNKNOWN.value

    def _angle_bucket(self, asset: Asset) -> str:
        if asset.head_pose_yaw is None:
            return "unknown"
        yaw = abs(asset.head_pose_yaw)
        if yaw < 15:
            return "front"
        if yaw <= 45:
            return "3quarter"
        return "profile"

    def _expression_bucket(self, asset: Asset) -> str:
        if (asset.face_count or 0) <= 0:
            return "none"
        return asset.dominant_emotion or "unknown"

    def _background_bucket(self, asset: Asset) -> str:
        if asset.is_indoor is not None:
            return "indoor" if asset.is_indoor else "outdoor"
        if asset.scene_class:
            return asset.scene_class
        return "unknown"

    def _compute_missing_coverage(self, assets: list[Asset]) -> list[str]:
        missing: list[str] = []
        if not assets:
            return ["Dataset is empty"]

        shot_counts: dict[str, int] = {}
        for a in assets:
            st = a.shot_type or "unknown"
            shot_counts[st] = shot_counts.get(st, 0) + 1

        if shot_counts.get("wide", 0) + shot_counts.get("full_body", 0) == 0:
            missing.append("Wide/full-body shots")
        if shot_counts.get("closeup", 0) + shot_counts.get("extreme_closeup", 0) == 0:
            missing.append("Closeup/extreme closeup shots")

        yaw_assets = [a for a in assets if a.head_pose_yaw is not None]
        if yaw_assets:
            has_profile = any(abs(a.head_pose_yaw) > 45 for a in yaw_assets)
            has_3q = any(15 <= abs(a.head_pose_yaw) <= 45 for a in yaw_assets)
            if not has_profile:
                missing.append("Profile (side) angle views")
            if not has_3q:
                missing.append("Three-quarter angle views")

        face_assets = [a for a in assets if (a.face_count or 0) > 0]
        if face_assets:
            emotion_counts: dict[str, int] = {}
            for a in face_assets:
                expr = a.dominant_emotion or "neutral"
                emotion_counts[expr] = emotion_counts.get(expr, 0) + 1
            smile_count = emotion_counts.get("happy", 0) + emotion_counts.get("smile", 0)
            if smile_count == 0:
                missing.append("Smiling/happy expressions")
            if emotion_counts.get("neutral", 0) == 0:
                missing.append("Neutral expressions")

        scene_assets = [a for a in assets if a.is_indoor is not None]
        if scene_assets:
            has_indoor = any(a.is_indoor for a in scene_assets)
            has_outdoor = any(not a.is_indoor for a in scene_assets)
            if not has_indoor:
                missing.append("Indoor/studio backgrounds")
            if not has_outdoor:
                missing.append("Outdoor backgrounds")

        return missing if missing else ["Coverage looks comprehensive"]

    def _compute_improvement_actions(self, issues: list[CoachIssue]) -> list[str]:
        severity_order = {
            IssueSeverity.CRITICAL: 0,
            IssueSeverity.HIGH: 1,
            IssueSeverity.MEDIUM: 2,
            IssueSeverity.LOW: 3,
        }
        sorted_issues = sorted(issues, key=lambda i: severity_order.get(i.severity, 99))

        actions: list[str] = []
        seen: set[str] = set()
        for issue in sorted_issues:
            action_text = f"[{issue.severity.upper()}] {issue.recommendation}"
            if action_text not in seen:
                seen.add(action_text)
                actions.append(action_text)

        return actions


async def analyze_dataset(project_id: str, db: AsyncSession) -> CoachReport:
    """Backward-compatible module-level function."""
    coach = DatasetCoach()
    return await coach.analyze(project_id, db)
