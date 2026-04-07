# Model / Provider Matrix

Legend:

- `CORE DEPENDENCY`
- `DIRECT CODE REUSE / VENDORED MODULE`
- `OPTIONAL PROVIDER`
- `ALGORITHM INSPIRATION`
- `UX INSPIRATION`
- `NOT RECOMMENDED`

## Sorting / Dataset Ops

| Repo | Classification | Capability | Reuse Decision | Risks / Notes |
| --- | --- | --- | --- | --- |
| `nazpins/naztech-automated-data-sorting-tools` | `ALGORITHM INSPIRATION` | automated folder/tag sorting | Reuse prompt/rule ideas only; do not vendor architecture. | Useful idea source, but Draco should own ingest and metadata model. |
| `peter119lee/sd-image-sorter` | `UX INSPIRATION` | dataset sorting UX | Reuse review workflow patterns, keyboard shortcuts, bulk triage ideas. | Good workflow inspiration, not a clean backend fit. |
| `bellingcat/smart-image-sorter` | `DIRECT CODE REUSE / VENDORED MODULE` | CLIP-style semantic sorting and zero-shot labeling | Reuse selected labeling and similarity workflow ideas behind a `ZeroShotClassificationProvider`. | Keep vendoring narrow; do not import app-level structure. |
| `MNeMoNiCuZ/ImageSorting` | `UX INSPIRATION` | manual folder sorting | Reuse only the fastest manual triage ideas. | Repo explicitly notes missing undo and weak GUI scaling; not suitable to vendor whole. |
| `Jelosus2/DatasetEditor` | `UX INSPIRATION` | dataset edit/review workflow | Reuse browse/edit/sidecar review patterns only. | Good product overlap, but Draco should keep its own architecture. |
| `summitsingh/ai-instagram-organizer` | `ALGORITHM INSPIRATION` | social-media-ready organization | Reuse taxonomy and organization ideas for media-library mode. | Narrow relevance to Draco core training workflows. |

## Ranking / Human Preference

| Repo | Classification | Capability | Reuse Decision | Risks / Notes |
| --- | --- | --- | --- | --- |
| `QuentinWach/image-ranker` | `DIRECT CODE REUSE / VENDORED MODULE` | pairwise image ranking | Reuse tournament/pair-comparison workflow concepts and any bounded rating utilities. | Vendoring only makes sense for narrowly scoped rating logic. |
| `jakeo-dev/pairckle` | `UX INSPIRATION` | pairwise comparison UI | Reuse interaction patterns for fast A/B review. | Better as frontend inspiration than as a dependency. |
| `onlaj/Kura` | `ALGORITHM INSPIRATION` | curation/ranking ideas | Reuse ranking workflow concepts only after verifying maintenance and license fit. | Keep out of core path unless a bounded subsystem proves clearly better. |

## Embeddings / Retrieval

| Repo | Classification | Capability | Reuse Decision | Risks / Notes |
| --- | --- | --- | --- | --- |
| `qdrant/fastembed` | `CORE DEPENDENCY` | local embeddings + vector search | Keep as the default embedding backend with Draco-owned provider wrapper. | Best current fit for local-first retrieval; lightweight and maintainable. |

## Face Analysis / Clustering

| Repo | Classification | Capability | Reuse Decision | Risks / Notes |
| --- | --- | --- | --- | --- |
| `exadel-inc/CompreFace` | `OPTIONAL PROVIDER` | hosted/local face API | Wrap as a provider for hybrid/hosted deployments; do not vendor service internals. | Excellent for REST-based deployment, but too heavyweight to import directly. |
| `serengil/deepface` | `OPTIONAL PROVIDER` | face attributes and fallback recognition | Wrap only as an optional Python provider. | Broad model coverage, but dependency footprint is heavy. |
| `tadasbaltrusaitis/openface` | `ALGORITHM INSPIRATION` | facial behavior analysis, AU/head pose | Reuse AU/head-pose methodology and output schema ideas. | Strong research value; high integration cost. |
| `cmusatyalab/openface` | `ALGORITHM INSPIRATION` | face embeddings / recognition | Reuse evaluation ideas only. | Historically important, but not the best modern default. |
| `deepinsight/insightface` | `CORE DEPENDENCY` | face detection + embeddings | Keep as the primary local face stack behind Draco providers. | Best fit for identity clustering and face-aware dedupe. |
| `ageitgey/face_recognition` | `OPTIONAL PROVIDER` | CPU fallback face recognition | Wrap as a CPU-safe fallback only. | Great compatibility fallback; not state-of-the-art for premium path. |
| `vladmandic/face-api` | `OPTIONAL PROVIDER` | browser/node face inference | Use only if Draco adds browser-side or Electron-side face inference. | Strong JS option, but secondary to Python backend providers today. |
| `yakhyo/uniface` | `ALGORITHM INSPIRATION` | unified face stack ideas | Reuse architecture ideas if needed; avoid early dependency adoption. | Better as reference until operational maturity is proven. |
| `biometrics/openbr` | `NOT RECOMMENDED` | legacy biometrics toolkit | Ignore for core product. | Old, heavy, and misaligned with Draco’s local-first modern stack. |
| `vectornguyen76/face-recognition` | `NOT RECOMMENDED` | small face recognition implementation | Ignore unless a tiny bounded utility is uniquely useful. | Lower confidence than better-supported alternatives. |
| `davidsandberg/facenet` | `ALGORITHM INSPIRATION` | classic face embedding pipeline | Reuse evaluation or embedding baseline ideas only. | Important historical reference, not the best present-day default. |
| `Faceplugin-ltd/Open-Source-Face-Recognition-SDK` | `NOT RECOMMENDED` | face recognition SDK | Avoid until license and maintenance posture are clearly safe. | License/provenance risk is too high for direct integration without deeper review. |
| `FacePerceiver/FaRL` | `ALGORITHM INSPIRATION` | face representation learning | Reuse research ideas for future attribute quality scoring. | Strong research value, high productization cost. |
| `ZhaoJ9014/face.evoLVe` | `ALGORITHM INSPIRATION` | face recognition training framework | Reuse training/evaluation ideas only. | Better as research reference than product dependency. |

## Training / Downstream Adjacency

| Repo | Classification | Capability | Reuse Decision | Risks / Notes |
| --- | --- | --- | --- | --- |
| `axolotl-ai-cloud/axolotl` | `OPTIONAL PROVIDER` | post-training / training orchestration | Reuse export or downstream handoff patterns only if Draco adds training-job launch support. | Useful adjacency, but not part of Draco’s core curation runtime. |

## Recommended Integration Summary

### Keep Or Strengthen

- `qdrant/fastembed`
- `deepinsight/insightface`
- `exadel-inc/CompreFace` as a wrapped provider, not vendored service code
- `ageitgey/face_recognition` as CPU fallback

### Reuse Narrowly

- `bellingcat/smart-image-sorter` for zero-shot sorting concepts
- `QuentinWach/image-ranker` for bounded ranking logic
- selected UX ideas from `sd-image-sorter`, `DatasetEditor`, and `pairckle`

### Do Not Pull In Whole-Repos

- manual-sorting apps with weak undo/scaling or tightly coupled GUI code
- legacy biometrics stacks
- unclear-license SDKs
- research/training repos that do not improve Draco’s curation runtime directly
