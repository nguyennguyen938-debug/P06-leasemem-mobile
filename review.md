# P06 — Four MobiSys reviews and meta-review

**Paper:** *Absent or Unchanged? What Android Tells a Cached-Fact Client After a Lifecycle Gap*  
**Review date:** 16 November 2026  
**Target:** MobiSys 2027, regular research paper  
**Meta-decision:** **Reject — borderline, with a credible measurement contribution but insufficient deployment validation.**

These are AI-generated author-feedback reviews, written as four distinct reviewer perspectives by one assistant. They are not independent human reviews or an actual program-committee decision. They assess the current measurement-oriented paper, including the verified deployment and two-model task experiments. They do not assume that the paper still claims a universally efficient new cache algorithm.

## Reviewed version, scope and scoring

The review covers the current LaTeX sections, generated evidence/deployment/task tables and PDF; selected artifact code, including `artifact/followup/agent_tasks.py`; and reported local package checks. No live experiment was rerun during this review, and no independently hosted artifact was retrieved.

PDF SHA-256: `b97faf856ac02b20a728d0b710907dd81678a3b721b02d18e1243d5b9e917424`.

Overall scale: **5 strong accept; 4 weak accept; 3 borderline; 2 weak reject; 1 strong reject**. Dimension scores run from 1, poor, to 5, excellent. Confidence runs from 1, low, to 5, expert-level certainty. These are simulated reviewer fields rather than verified official HotCRP scales.

The [MobiSys 2027 CFP](https://www.sigmobile.org/mobisys/2027/call_for_papers/) is the venue basis for this assessment. Current source/log/PDF checks show 10pt, Xuan-Bach Le in Author metadata, US Letter pages and references beginning on page 12. Local QA reports 53 review lines per column. The LLM disclosure is present. Earlier anonymous/9pt formatting complaints are not current findings; every rendered figure and column was not independently visually certified in this pass.

## Paper and evidence map

The paper asks what an Android client can infer about cached facts after process death, lost observation or delayed callbacks. It measures seven source types, shows why optimistic value/version anchoring can fail, defines a conservative certificate contract, and compares practical refresh and memoization strategies. Its strongest conclusion is a boundary: notifications are hints, stock stamps need explicit contracts, and cheap current-input reads often beat validation.

| Claim or experiment | Current evidence | Interpretation |
|---|---|---|
| Lifecycle and deployment state affect callbacks | Seven-source campaigns plus 180 verified deployment trials | Background delay, freezing, FGS and bound-assistant state are separated more carefully. The verified deployment matrix is Contacts-only, not all seven sources. |
| Read-then-stamp anchoring can certify an old value | 280 stock-source trials; 78 stale FRESH outcomes for optimistic anchoring | A controlled counterexample to the optimistic client. Strict stock adapters return UNKNOWN; they do not recover a useful certificate in these trials. |
| Consistent evidence can certify a query snapshot | 560 cooperative-reference trials and an independent snapshot oracle | Establishes conformance for the implemented managed-writer contract. Not proof that stock providers expose that contract. |
| Weak stamps and identity reuse matter | Same-metadata files, clock restoration, SMS reuse, reset and fallback tests; 4,000 rapid call-log edit/read pairs | Concrete failures and conservative fallbacks. Zero equal-tick call-log changes observed does not establish a strict timestamp guarantee. |
| Event-only strategies can miss in-epoch changes | Body trial table: 22/124 background Android 13 trials and 16/24 background Android 15 trials for restart-aware events | Rates are conditional on staged timing and configuration. Facts within a trial are not independent samples. |
| Validation is not inherently cheaper than refresh | 180 paired matched-helper trials | Shared transport and residency largely remove the earlier host-transport advantage. Relay is cheaper but has a different liveness/freshness contract. |
| Revalidation cannot make the later action atomic | Controlled boundary experiment and 40 cooperative action-residual trials | Correctly distinguishes certification time from later effects. No conditional action API is implemented. |
| Real LLM reuse can save work | 144 paired trials across Qwen2.5-7B and Llama-3.2-3B, three draft tasks, three schedules | Real generation and Android file effects; memoization wins. No AndroidWorld completion or semantic text-quality result. |
| Reproducibility | 490 manifest files, 27 generated outputs unchanged and identical PDF text in local clean extraction | Useful reported local verification, not an independent external reproduction. |

## Context, novelty and gap audit

Eight targeted primary sources were checked. The paper already covers these lines of work; the main gap is distinguishing its empirical contribution from documented mechanisms and established validation ideas.

| Verified source | Relationship and implication |
|---|---|
| [AOSP ContentService implementation](https://android.googlesource.com/platform/frameworks/base/+/master/services/core/java/com/android/server/content/ContentService.java) | Defines a background-observer delay of ten seconds. Measuring the constant alone is not a new discovery; deployment interactions and consequences must carry the contribution. |
| [AOSP cached-app freezer documentation](https://source.android.com/docs/core/perf/cached-apps-freezer?hl=en) | Freezing is a known resource-management behavior. The paper adds state-verified callback observations and distinguishes frozen from unfrozen timing. |
| [MediaStore API](https://developer.android.com/reference/android/provider/MediaStore) | Generation comparison is associated with checking the overall version. This motivates explicit incarnation/reset handling, not an assumption that arbitrary query and generation reads are one snapshot. |
| [Contacts RawContacts API](https://developer.android.com/reference/android/provider/ContactsContract.RawContacts) | Row versions support optimistic locking. A row-version field alone does not establish a complete, reset-safe, multi-read certificate for every query. |
| [Kung and Robinson, On Optimistic Methods for Concurrency Control, 1981](https://www.cs.cmu.edu/~natassa/courses/15-721/papers/p213-kung.pdf) | The validation pattern is established. The current paper appropriately treats its contract as an application of optimistic validation rather than a new algorithm. |
| [MobileGPT, MobiCom 2024, author project](https://mobile-gpt.github.io/) | Demonstrates procedural app memory for mobile tasks. Procedural reuse and certification of changing provider facts are distinct; the paper should not imply all agent memory depends on stale facts. |
| [AndroidWorld, ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/hash/01a83bc2f2732a58e6aa731e659e7101-Abstract-Conference.html) | Provides initialized tasks and state-based success checks. Inspecting selected validators is useful provenance analysis, but it is not executing that benchmark. |
| [Rethinking Process Management for Interactive Mobile Systems, MobiCom 2024](https://feng-qian.github.io/paper/sur_mobicom24.pdf) | Large OEM deployment work shows why process-management assumptions deserve deployment-specific validation. It does not establish this paper's callback numbers or require an equally large study. |

**Novelty judgment.** The contribution is an empirical map and a set of counterexamples at Android source/lifecycle boundaries. Neither optimistic concurrency control nor the general observation/action race is new. The strongest potential insight is that an apparently useful stock-provider validation path can fail both correctness and cost tests once its observation protocol and transport are made fair.

**Baseline judgment.** Batched refresh, batched validation, a notification relay, current-input memoization and actual two-model draft executions are already present. It would be incorrect to ask for them as wholly missing. The remaining comparison is under genuinely representative tasks, current device states and overlapping mutation, with each arm judged at a well-defined instant.

**Theory judgment.** The explicit query-snapshot instant and UNKNOWN fallback repair earlier overclaims. For a measurement paper, a new conditional action primitive is optional, not an acceptance prerequisite. The paper should be judged on whether its measurements and recommendations teach something important beyond the established principles it applies.

## Reviewer 1 — Android platform measurement

**Overall: 4/5, weak accept. Confidence: 4/5.**

### Summary

This paper explains why absence of a callback is not evidence that a remembered fact is unchanged. It combines source-specific stamp analysis, lifecycle experiments, state-verified callback measurements and cost comparisons. Its practical conclusion—that direct refresh and current-input memoization are often preferable—is valuable precisely because it contradicts an attractive but unreliable cache-validation design.

### Strengths

The paper separates lost observer coverage from delayed delivery within one process incarnation. Restart-aware invalidation handles the former but does not fix the latter. The trial-level table makes this distinction visible without treating every fact use as an independent replication.

The deployment diagnosis is much stronger than simply reporting Android-version differences. With freezing disabled and state verified, both Android 13 and 15 have approximately ten-second background delay. FGS and bound-assistant callbacks are much faster. Frozen trials verify the cgroup and distinguish the hold from delivery after thaw. The previous mixed-state Android 15 measurements are not promoted to a new platform constant.

The observation race is a concrete systems finding. Reading a fact and then a newer watermark can attach the wrong evidence to the old value. The stock-source counterexamples make the problem tangible; the strict path conservatively returns UNKNOWN rather than claiming an unsupported repair.

Finally, the cost experiments are unusually willing to accept negative results. Refresh wins on cheap local queries, the matched host helper eliminates a misleading transport advantage, and input memoization saves actual resumed model work. These are useful recommendations for practitioners.

### Weaknesses and implications

The verified deployment matrix uses Contacts, whereas the broader source matrix contains seven different notification and persistence behaviors. The paper needs to make it effortless to see which source/deployment combinations were actually measured. A reader should not extrapolate a Contacts-only assistant result to arbitrary private app databases or files.

All runtime work is on emulators sharing a host. Freezing, process priorities, pressure, current-target FGS behavior and energy are exactly the areas in which deployment differences matter. The API-35 typed-FGS test establishes a foreground-start case, not background-start eligibility or long-duration operation. The persistent system process is also a privileged reference, not a normal installation option.

The ten-second delay is present in platform source. The paper should therefore lead with the interaction and the strategy-selection consequence, not the apparent rediscovery of a constant. The negative validation and anchoring results are more distinctive.

### Questions for the authors

- Which entries in the source/deployment matrix have direct runtime evidence, and which are inferred from APIs or source?
- How do the main recommendations change for a bound assistant on a current physical device?
- Can the existing conditional-strategy table in §8 link each recommendation to the exact source/deployment evidence and unsupported cases?

### Recommendation

Weak accept as a measurement paper. I do not require the authors to make strict certificates faster or useful on unsupported sources. I would support bounded shepherding on presentation and scoped guidance, while treating current-device replication as the most valuable additional evidence.

## Reviewer 2 — Consistency contracts and correctness

**Overall: 3/5, borderline. Confidence: 4/5.**

### Summary

The paper distinguishes an optimistic stamp-based client from a conservative protocol that certifies a specific query snapshot only when the provider contract is sufficient. This is a sound and important correction. My concern is that the strict stock path obtains safety by refusing certification everywhere, leaving the practical contribution in the measurement and fallback analysis rather than in a usable stock-provider validation mechanism.

### Strengths

The consistent-evidence contract explicitly binds a value to an incarnation and version. The before/after evidence protocol covers query, support and delta reads, not just a final scalar watermark. Reset, identity reuse and retry exhaustion lead to UNKNOWN. The managed reference provider supplies a concrete positive case rather than relying entirely on vacuous rejection.

The independent oracle checks logged snapshots and attempt sequences rather than merely trusting the Java verdict. Its 560 reference trials include successful certificates, detected changes and conservative failures. This is more informative than reporting a single “zero errors” total.

The manuscript names the certified instant and separates it from the later action. The 40 action-residual trials demonstrate that a correct earlier certificate can coexist with a stale later effect. That is a limitation of the action interface, not a contradiction of the stated certificate theorem.

### Weaknesses and implications

**Stock usefulness remains zero in the strict evaluation.** The 280 stock trials all return UNKNOWN. This avoids unsound certificates, but it does not show a generally usable stock-provider cache-validation protocol. The positive certificate evidence comes from a provider controlled by the experiment. This is appropriate for conformance, yet the paper must keep “implemented reference contract” and “available Android contract” visually distinct.

**A certificate over a query does not certify an arbitrary derived action.** Complete dependency capture, deterministic interpretation of those inputs, and the semantics of the output are separate obligations. The draft experiment checks structured inputs and nonempty text, not whether the text actually reflects the new facts. A generated draft can retain a stale semantic statement while carrying correct input fields. The manuscript acknowledges that it does not score language quality; the discussion should explain the resulting boundary for agent safety.

**Cross-source consistency is unresolved.** Separate fresh reads from Contacts, MediaStore and Calendar do not establish that the combined inputs coexisted at one instant. The paper does not promise a joint snapshot, which is correct. Nevertheless, the workload guidance should identify tasks that tolerate such mixtures and tasks that require a transaction or a final conditional effect.

**Established theory limits algorithmic novelty.** The contribution is showing where Android does or does not meet familiar assumptions. The proof is useful for claim discipline, but it should occupy space proportional to that role.

### Questions for the authors

- Can any supported stock query receive a strict certificate under an explicitly justified, narrower contract?
- Which task properties require a joint snapshot, and which only require separately refreshed inputs?
- What exactly is covered by “stale action”: old structured inputs, stale generated semantics, or both?

### Recommendation

Borderline. The formal boundary is now credible, but full-paper acceptance depends on the measurement's significance. I would not demand a new conditional commit API to repair a claim the current paper no longer makes.

## Reviewer 3 — Evaluation breadth and statistical inference

**Overall: 2/5, weak reject. Confidence: 4/5.**

### Summary

The paper contains substantial controlled evidence and several good methodological corrections. It still has a limited basis for recommendations across mobile deployments, because its independently sampled units are emulator trials with selected schedules rather than devices, applications or naturally occurring interruptions. Some central negative findings are structurally determined by the tested policy definitions.

### Strengths

The body now reports stale-trial counts and Wilson intervals. For example, zero stale trials among 24 gives a 13.8% upper endpoint, while zero among 125 gives 3.0%. This makes clear why a pooled fact-use count would overstate certainty.

The matched helper randomizes arm order, uses the same transport, serialization, privileges and residency, and resamples paired trials. Most validation-versus-refresh confidence intervals overlap zero. This is a much fairer comparison than separate shell invocations.

The deployment checks and retained invalid runs address configuration failures that could otherwise masquerade as Android behavior. Continuous writers are included in the host experiment, and ambiguous later-value differences are not mislabeled as proven stale-at-certification failures.

### Weaknesses and implications

**The continuous-mutation study does not close the correctness question for real tasks.** The matched host study correctly calls comparisons to later reads ambiguous. The actual LLM task experiment then uses quiescent provider truth after scripted mutations. Neither yields an end-to-end measurement of concurrent source updates during observation, validation, model execution and effect. A log-based source/effect history could separate values certified at read time from values valid at dispatch without inventing a single impossible “current” timestamp.

**The three task arms are not equally informative about policy efficacy.** Strict evidence on stock adapters always falls back to reading and regenerating. Refresh does the same expensive work. Memoization compares the complete current input and reuses an equal-input output. Its advantage is therefore expected in a deliberately low-change workload. The actual latency measurement is useful, but the experiment does not show a nontrivial strict reuse regime or a hard agent decision problem.

**Hardware and workload replication remain absent.** Multiple AVDs on one Apple-silicon host do not characterize OEM callback behavior, real energy or deployment restrictions. Android 13/15 comparisons and two local LLMs give software diversity, not independent device evidence. The phone constraint is openly acknowledged, but it remains material to a mobile measurement submission.

**Averages across tasks and schedules hide where the benefit arises.** The task table aggregates 72 trials per model/policy. Report paired differences by task, gap and change outcome, with uncertainty. The 0/72 stale-action bound is conditional on that mixture and cannot support claims about arbitrary agent tasks or continuously mutating use.

### Questions for the authors

- How do memoization savings vary by actual changed-input status and task, rather than only by model?
- Can continuous mutation be evaluated with a timestamped oracle that separates observation, certification and effect failures?
- Which major conclusions survive a current physical-device replication with logged process and binding state?

### Recommendation

Weak reject. I would prioritize a small, carefully controlled current-phone replication and a realistic task/provenance study over more repetitions of fixed injected schedules. The present paper is candid, but candid limitations do not by themselves supply the missing external evidence.

## Reviewer 4 — Mobile agents, workload relevance and reproducibility

**Overall: 3/5, borderline. Confidence: 3/5.**

### Summary

The paper's value for agent developers is its warning against treating notifications or weak stamps as freshness certificates. It now includes real model calls and Android effects, and correctly recommends current-input memoization when it wins. I am less convinced that the selected tasks demonstrate how frequently this issue matters in an actual mobile agent's memory and action pipeline.

### Strengths

The two-model experiment is real execution, not a sum of isolated inference timings. It measures the resumed suffix through input acquisition, generation or reuse, file writing and readback. The shared prefix and gap are explicitly outside the timer. Qwen's medians are 2.29 seconds for refresh and 0.29 for memoization; Llama's are 0.89 and 0.29. The paper does not call those figures complete user-session latency.

The selected AndroidWorld validator inspection is appropriately skeptical. A task name is not evidence that an agent needs a cached provider fact; some goals already contain the needed recipient or text. Reporting UNKNOWN for unsupported queries is more defensible than claiming coverage from an app-store census.

The artifact retains model requests/responses, actual saved contents, hashes, state checks and independent oracle logic. Its reported clean package regeneration and failure-preserving workflow are useful foundations for reproducibility.

### Weaknesses and implications

The agent prompt is a constrained JSON drafting task: copy task identity and inputs, then produce a useful sentence. The measured Android effect is an ADB-mediated draft-file write. This is a valid experiment for a tool-using pipeline, but it does not exercise app navigation, ambiguous task decomposition, user-facing dispatch, permission changes during a task or naturally evolving memory. The paper should not imply that all 72/72 successes measure general mobile-agent competence.

The success oracle requires correct structured fields and nonempty text. It does not assess whether the sentence is semantically current, appropriate or useful. This matters because the manuscript motivates expensive derived facts. Reusing a generated answer safely requires knowing what it depends on, including dependencies not represented by the hand-selected input keys.

The nine inspected validators are selected examples. They reveal that task-name coverage was too optimistic, but they cannot estimate the fraction of agent tasks for which durable evidence would be helpful. A representative task/provenance sample would give the negative result a clearer scope.

Finally, the artifact's reported clean extraction reuses an existing toolchain. The review has not independently downloaded or executed it. A fresh reader should be able to reproduce a small callback/anchoring case before setting up the entire model environment.

### Questions for the authors

- How are dependencies discovered for actual agent-generated outputs rather than supplied in advance by the fixture?
- Can one representative existing agent workflow expose a stale fact, show its real effect and compare refresh/memoization under the same task contract?
- Can the minimal reproduction avoid large model downloads for readers interested primarily in the platform result?

### Recommendation

Borderline. The platform evidence is potentially publishable on its own; the agent component should either be a tightly scoped demonstration or be grounded in a more representative workflow. I would not make a claim of general agent safety from the current draft-file tasks.

## Scores across perspectives

| Dimension | R1 platform | R2 correctness | R3 evaluation | R4 agents/artifact |
|---|---:|---:|---:|---:|
| Originality | 4 | 3 | 3 | 3 |
| Importance | 4 | 4 | 4 | 4 |
| Claim support | 4 | 4 | 3 | 3 |
| Experimental soundness | 4 | 4 | 2 | 3 |
| Writing clarity | 3 | 3 | 3 | 3 |
| Community value | 4 | 4 | 3 | 4 |
| Contextualization | 4 | 4 | 4 | 4 |
| **Overall recommendation** | **4** | **3** | **2** | **3** |
| **Confidence** | **4** | **4** | **4** | **3** |

## Writing and logic audit

- **Keep one measurement thesis.** The best story is when Android evidence is unavailable, delayed or unsafe to interpret, followed by a strategy table. Do not let the reference certificate look like a universally available stock feature.
- **Visually distinguish three evaluations.** StampCheck is an optimistic baseline; EvCheck on the cooperative reference can certify; EvCheck on stock adapters falls back. A zero-miss result in one should never be read as evidence for another.
- **Use state, not just Android version, to explain latency.** The old Android 15 delays include mixed freezer state. The verified approximately ten-second unfrozen result is Contacts-specific evidence with a known platform explanation.
- **Name the correctness instant each time.** Query snapshot, validation return, model output and Android effect are different boundaries. A post-trial value is not automatically an oracle for an earlier concurrent read.
- **Label agent success precisely.** “Exact structured-goal success” is supported. “Semantically correct draft” or “AndroidWorld completion” would not be.
- **Keep negative results prominent.** Direct refresh and input memoization winning are findings, not qualifications to hide after a mechanism pitch.
- **Reduce cognitive load.** Extend the existing conditional-strategy table in §8 with source/deployment evidence and contract status, and connect it to the source and deployment tables in §3. This would be more useful than another long sequence of named campaigns. Keep raw diagnostic history in the artifact.

## Meta-review

### Decision: Reject — borderline

The reviewers agree that the paper now makes a defensible, measurement-oriented contribution. It no longer relies on non-atomic anchoring as a sound certificate, treats unsupported stock contracts conservatively, defines the certified instant, reports trial-level uncertainty and uses fair host transport. The verified deployment matrix and real two-model task suffixes are substantive additions. It would be incorrect to reject this version for lacking those elements.

Reviewer 1 supports acceptance because the negative results and operational map can improve mobile-system design. Reviewers 2 and 4 are borderline: they find the contract and artifact useful but question how much practical stock-provider or agent capability has been established. Reviewer 3 places greater weight on emulator-only deployment evidence, selected task inputs and the absence of an end-to-end concurrent-mutation oracle.

On balance, I lean reject for the regular-paper track. The known background delay, familiar optimistic-validation requirements and expected advantage of memoizing equal current inputs are not individually enough. The paper's original value lies in the measured interactions and counterexamples. That value would be more convincing with current-device replication and a representative task/provenance sample showing where the recommendations materially change a deployed workflow.

This is not a demand that the authors make a speculative certificate algorithm outperform refresh. A new conditional action API is also not required for the chosen measurement thesis. The decision concerns the breadth and importance of the measured conclusions, not the absence of a mechanism the paper explicitly leaves outside scope.

I would not label the paper conditionally accepted if acceptance depends on obtaining phones and discovering a new realistic agent case after notification. Those are meaningful scientific tasks. If a PC values the controlled platform map as sufficient, Reviewer 1's weak-accept position is reasonable; the decision is genuinely close.

**Subjective acceptance band:** approximately **25–45%**, with low confidence in the numerical band. A small, well-controlled current-phone replication and a more representative dependency/task study would move it upward. Increasing the number of identical draft tasks or trying to manufacture a validation speedup would have much less impact.

## Prioritized checklist

### P0 — Submission readiness

- [x] Current source/log use 10pt, PDF Author is Xuan-Bach Le, and references start on page 12.
- [x] Single-blind front matter and LLM-assistance disclosure are present.
- [ ] Recheck rendered layout after edits; keep the trial-level counts, matched transport and principal counterexamples in the body.
- [ ] Complete conference registration/submission; neither action was performed by this review.

### P1 — Decision-critical work

- [ ] Replicate the principal callback and source-contract findings on a current physical device, recording exact OS, provider, target SDK, process state, binding and freezer state. Handset validation remains open under the current emulator-only work constraint.
- [ ] Connect the existing body source, deployment and strategy tables with an explicit evidence-coverage matrix, distinguishing seven-source measurements from the Contacts-only verified deployment campaign.
- [ ] Ground the practical recommendation in a representative existing task or app workflow, including actual queries, dependencies, gaps and effects. Do not infer coverage from task names.
- [ ] Evaluate overlapping mutations through observation, validation and effect with a timestamped oracle that can distinguish certified-snapshot correctness from later-action staleness.
- [x] Separate stock UNKNOWN/fallback results from positive cooperative certificates, and state that the current strict stock path demonstrates no certified reuse. Preserve this distinction in subsequent edits.
- [ ] Report paired task-latency differences by task, schedule and changed-input status; preserve within-trial correlations and conditional zero-result denominators.

### P2 — Strongly recommended

- [ ] Explain which multi-source tasks tolerate independently refreshed values and which require a joint snapshot or conditional effect.
- [ ] Validate generated-text semantics or keep the task-success metric strictly limited to structured inputs, task identity and nonempty output.
- [ ] Extend realistic current-target service tests to the intended background-start and duration regime before claiming general deployability.
- [ ] Report physical energy only from a physical measurement; retain the emulator BatteryStats label otherwise.
- [ ] Provide a minimal callback/anchoring reproduction independent of LLM setup, then verify full artifact retrieval and bootstrap with an independent reader.
- [ ] Preserve invalid runs, configuration checks, raw snapshot histories, negative oracle tests and deterministic generation instructions.

### P3 — Optional strengthening

- [ ] Explore a genuinely supported narrow stock-provider certificate if a precise contract can be established; do not infer it from zero failures alone.
- [ ] Package the adapter conformance suite with explicit expected outcomes for resets, concurrent reads, same-tick updates, deletion/reuse and unsupported sources.
- [ ] Broaden the actual task/provenance sample and dependency discovery study.
- [ ] Keep a conditional action API as a separately scoped extension rather than a retroactive requirement for this measurement paper.
