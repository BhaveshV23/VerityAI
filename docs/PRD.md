# VerityAI Product Requirements Document

## 1. Document information and status

| Field | Value |
|---|---|
| Product | VerityAI |
| Document | Product Requirements Document (PRD) |
| Version | 0.4 |
| Status | Draft for product review |
| Product stage | Hackathon; MVP target: Round 2 |
| Last updated | 2026-11-05 |
| Owner | OPEN — product owner to be named |

This document describes product behaviour and acceptance expectations. It does not select technologies or prescribe architecture. Items marked **OPEN** require a product decision before the affected capability is finalised.

### Revision history

| Version | Date | Summary |
|---|---|---|
| 0.4 | 2026-11-05 | Harmonised evidence lifecycle states and independent conditions; clarified freshness eligibility, Inactive handling, validity re-approval, and immutable submission versions versus derived processing data. |

## 2. Executive summary

VerityAI is a human-supervised content governance platform that helps organisations review claims in marketing and business content against approved organisational evidence and defined brand policies. It links each finding to its claim, supporting or missing evidence, applicable policy and review decision, so reviewers can understand the basis of the result.

The MVP (Round 2) demonstrates one end-to-end workflow: an organisation manages guidelines and evidence; a creator submits text or a document; VerityAI identifies claims, retrieves and matches evidence, applies basic deterministic policy checks, and presents explainable findings and suggestions; a human reviewer requests changes, approves, approves with documented exceptions, or rejects; and the system records the outcome for history and basic governance insights.

AI assistance may identify and interpret content, but an AI confidence score is never proof that a claim is true. Missing evidence means unverified, not false. Important decisions remain with authorised people. VerityAI does not publish content automatically or certify legal or regulatory compliance.

## 3. Product vision and objectives

### Vision

Give organisations a traceable, consistent way to establish whether important content claims have an adequate evidence and policy basis before people approve the content for use.

### Objectives

- Connect submitted claims to approved sources with ownership and validity context.
- Make policy checks and review findings understandable and traceable.
- Route uncertain, conflicting, or sensitive decisions to authorised humans.
- Preserve review decisions and history so organisations can identify recurring governance problems.
- Demonstrate a coherent, usable content review lifecycle within the Round 2 MVP.

### Product positioning

VerityAI’s intended differentiation is the integrated relationship between a content claim, approved evidence, evidence validity and ownership, policy consistency, explainable findings, human decisions, and governance improvement. This is a product focus and hypothesis, not a claim that other products lack these capabilities.

## 4. Problem statement and context

Organisational product facts, approved evidence, brand guidelines, and review decisions are often distributed across documents and teams. As the volume and pace of content increase, reviewers may not be able to locate the right sources or apply guidance consistently. As a result, unsupported or outdated claims, inconsistent messaging, and ambiguous policies can pass through review or repeatedly consume reviewer time.

Manual review remains necessary for judgement and authority, but it is difficult to scale without a traceable record of the material reviewed, the sources and rules considered, and the human decision. VerityAI supports that process by organising evidence and policy checks around claims and making uncertainty visible.

Absence of evidence is not evidence of falsity. An automated match or suggestion is not an authoritative verification. The platform supports governance and review; it does not replace accountable subject-matter, legal, compliance, or brand reviewers.

## 5. Target users and personas

| Persona | Responsibilities | Goals | Typical interaction |
|---|---|---|---|
| Content creator | Drafts and submits content; responds to requested changes | Resolve issues early and understand what needs attention | Creates a submission, reviews findings, edits, resubmits |
| Brand manager | Owns brand guidance and messaging standards | Apply consistent guidance and clarify ambiguous rules | Maintains policies, reviews policy findings, resolves or escalates ambiguity |
| Evidence/product owner | Maintains product facts and their supporting sources | Keep approved evidence accurate, owned, and current | Adds or updates evidence, assigns ownership and validity, resolves evidence conflicts |
| Compliance reviewer | Reviews sensitive or higher-risk claims and content | See the basis, limitations, and history of a review | Examines evidence and policy links, records a decision or requests changes |
| Organisation administrator | Configures the workspace, membership, and role assignments | Control access and establish organisation-level governance | Invites/deactivates users, assigns roles, manages workspace settings |

One person may hold multiple responsibilities. MVP role assignment is workspace-scoped. Whether one account can hold multiple roles is **OPEN**.

## 6. User needs and pain points

- Creators need specific, actionable findings tied to the relevant text, not an unexplained overall score.
- Reviewers need to open the source behind a finding and see its approval status, owner, and validity information.
- Evidence owners need to know which sources are missing, expired, or in conflict and which claims or reviews use them.
- Brand managers need to distinguish an actual rule violation from a rule that is ambiguous or conflicts with another rule.
- Administrators need predictable role boundaries and an auditable record of material changes and decisions.
- Organisations need to learn which issues recur without automatically changing official policies.

## 7. Product principles

1. **Evidence over unsupported confidence:** evidence links and status determine the evidence basis; model confidence never proves truth.
2. **Explainable findings:** each finding identifies the content at issue and the evidence or policy basis, or states that no applicable basis was found.
3. **Human authority:** authorised people resolve consequential uncertainty and make review decisions.
4. **Visible uncertainty:** missing, expired, conflicting, ambiguous, or low-confidence inputs are represented explicitly.
5. **No fabricated authority:** the system must not invent sources, policies, owners, or verification dates.
6. **Privacy and security:** organisational content and sources are accessible only to authorised workspace users.
7. **No automatic publication:** review completion does not publish or distribute submitted content.
8. **No certification claims:** findings do not constitute legal, regulatory, or compliance certification.
9. **Governance changes require authorised humans:** recommendations do not change official policy or evidence status on their own.

## 8. Product scope

### MVP — Round 2

The MVP includes a single organisation workspace; basic user roles and permissions; guideline and evidence management; text and PDF/DOCX submission; claim extraction; evidence retrieval and matching; basic deterministic policy checks; explainable findings and suggested corrections; human review and revision cycles; review history and audit records; and basic governance insights derived from recorded reviews.

MVP supports an English-language workflow. PDF/DOCX ingestion is included as an input requirement, subject to usable text extraction; scanned-image OCR is not required for MVP. The initial demonstration may use a fictional fintech organisation.

To keep the end-to-end workflow feasible, MVP analysis is limited to extractable text, candidate claims, retrieval from explicitly approved evidence, and a small set of configured deterministic terminology/messaging checks. Evidence conflicts are manually recorded; policy ambiguity is manually flagged or surfaced only when explicit deterministic rules collide. Evidence approval is a simple authorised owner action rather than a multi-stage approval workflow. Governance insights are the five direct-count metrics in §16, with no predictive analysis or configurable analytics. These simplifications retain the evidence-to-policy-to-human-decision lifecycle; OCR, automatic conflict discovery, advanced claim taxonomies, and disagreement analytics remain outside MVP.

### Round 3 / next release

- Improved claim classification, evidence matching, conflict detection, and evidence freshness handling.
- Richer policy authoring, versioning, ambiguity detection, and authorised clarification workflows.
- Expanded governance analysis, filters, trends, and reviewer disagreement views.
- More robust document ingestion and operational controls based on MVP learning.
- Further role granularity and configurable review routing, if validated.

### Future roadmap

- Visual and image-based claim analysis.
- Additional languages and locale-specific guidance.
- CMS and content workflow integrations.
- Continuous monitoring of published content and change detection.
- Enterprise identity, retention, and administration capabilities beyond MVP needs.
- Expanded analytics and configurable governance reporting.

Roadmap items are directional, not committed delivery dates or detailed specifications.

## 9. Functional requirements

Priority labels: **MUST (MVP)** is required for the Round 2 workflow; **SHOULD (next)** is targeted for a subsequent release; **FUTURE** is outside the MVP.

### Workspace and access

- **FR-001 — MUST (MVP):** The system shall provide an organisation workspace that scopes its members, submissions, evidence, policies, review records, and insights.
- **FR-002 — MUST (MVP):** An organisation administrator shall be able to add or deactivate workspace members and assign available workspace roles.
- **FR-003 — MUST (MVP):** The system shall deny access to workspace records to users who are not members of that workspace.
- **FR-004 — MUST (MVP):** The system shall record the actor and time for changes to evidence, policies, membership/role assignments, and review decisions.

### Evidence and policy management

- **FR-005 — MUST (MVP):** An authorised evidence/product owner shall be able to register and view an evidence record, including a title, source reference or attached document, owner, status, and validity dates where known; upload or registration shall not imply review or approval.
- **FR-006 — MUST (MVP):** An authorised brand manager or administrator shall be able to create and maintain policy records with a name, rule text, category, status, and version or change history.
- **FR-007 — MUST (MVP):** The system shall represent **Uploaded**, **Reviewed**, and **Approved** as primary evidence lifecycle states, and **Inactive**, **Expired**, and **Conflict-flagged** as independent evidence conditions, as defined in §12. Upload shall never imply review or approval. Only Approved evidence with no blocking validity bound and no Inactive or Conflict-flagged condition may be presented as eligible approved support. Unknown freshness alone does not block eligibility and must be disclosed.
- **FR-008 — MUST (MVP):** The system shall preserve the policy and evidence record versions used by a completed review, or otherwise retain an immutable review snapshot sufficient to explain that review later.

### Submission and analysis

- **FR-009 — MUST (MVP):** A creator shall be able to submit pasted English text or upload a PDF/DOCX document for review.
- **FR-010 — MUST (MVP):** The system shall retain the exact submitted text or a reference to the exact originally uploaded document as a submission version, and associate it with a submitter, workspace, submission time, and review status. Once created, the source content/version shall not be overwritten.
- **FR-011 — MUST (MVP):** The system shall extract candidate factual or promotional claims and associate each candidate with the exact submission version and analysis result, and with a location or text span in the submitted content when available.
- **FR-012 — MUST (MVP):** The system shall search only evidence that is Approved, has no blocking validity bound, and is neither Inactive nor Conflict-flagged as eligible approved support, and present candidate claim-to-evidence matches with source details and an explanation of the match basis. If validity information is missing, the system shall disclose freshness as unknown; this alone does not exclude otherwise eligible Approved evidence. A supplied future effective date or passed expiry date blocks eligibility. Uploaded or Reviewed evidence is not eligible approved support.
- **FR-013 — MUST (MVP):** The system shall flag a claim for human attention when no relevant approved evidence is found; the finding shall say “unverified” or equivalent and shall not label the claim false solely due to absent evidence.
- **FR-014 — MUST (MVP):** The system shall identify evidence that is Expired, not yet effective, Inactive, or Conflict-flagged and shall not use it as eligible approved support. It shall disclose missing validity information as unknown freshness; unknown freshness alone does not make otherwise eligible Approved evidence ineligible. Contextual warnings and freshness information shall be clearly distinguished from the evidence eligibility decision. Conflict flags are manually recorded in MVP; the system shall not claim to discover evidence conflicts automatically.
- **FR-015 — MUST (MVP):** The system shall run configured deterministic policy checks for defined terminology and messaging rules and link any triggered finding to the relevant policy version.
- **FR-016 — MUST (MVP):** The system shall present findings with a category, affected content, severity or attention level, explanation, supporting source or policy link when applicable, and an optional suggested correction.
- **FR-017 — MUST (MVP):** The system shall label suggestions as machine-generated suggestions and shall not represent them as verified facts or approved policy.
- **FR-018 — SHOULD (next):** The system should automatically identify possible contradictory evidence and present the competing sources and relevant differences for human review. This automated detection is next-release scope.
- **FR-019 — SHOULD (next):** The system should identify potential policy ambiguity or conflict and present the relevant policy versions and rules for authorised clarification.

### Review, history, and governance

- **FR-020 — MUST (MVP):** An authorised reviewer shall be able to record one of four decisions for a submission: **Approved**, **Approved with documented exceptions**, **Rejected**, or **Changes requested**. The reviewer shall include rationale as defined in FR-030.
- **FR-021 — MUST (MVP):** A creator shall be able to submit a revised version after changes are requested; the system shall preserve the prior version and its findings and decision history.
- **FR-022 — MUST (MVP):** The system shall provide a chronological review history showing submission versions, findings, evidence/policy references, actors, timestamps, and decisions.
- **FR-023 — MUST (MVP):** The system shall provide the five defined MVP governance metrics in §16: submission and review counts, unverified claims, recurring policy findings, review decision trends, and evidence requiring attention. Metrics shall use recorded workspace data and show their period and data limits.
- **FR-024 — MUST (MVP):** The system shall label governance insights as descriptive signals from recorded reviews and shall not automatically modify policies or evidence.
- **FR-025 — SHOULD (next):** The system should surface recurring reviewer disagreement and guidance clarification patterns where the recorded data supports them.
- **FR-026 — FUTURE:** The system may monitor published content through external content integrations and identify changes that warrant renewed review.

## 10. Detailed end-to-end user workflows

### A. Workspace setup

1. An organisation administrator creates or opens the organisation workspace.
2. The administrator adds members and assigns roles.
3. A brand manager adds applicable guidelines as policy records. An evidence/product owner registers evidence; its primary lifecycle begins in Uploaded and it is not eligible as approved support until a responsible person reviews and explicitly approves it.
4. The system records each material change and makes Approved evidence eligible for new reviews only when no supplied validity bound blocks it and it is neither Inactive nor Conflict-flagged. Missing validity information is shown as freshness unknown but does not by itself block eligibility. Setting or clearing Inactive changes only that independent condition; it never changes the primary lifecycle state. A validity-date change creates a revised evidence version, which remains ineligible until explicitly re-approved.

### B. Content submission and automated analysis

1. A creator enters text or uploads a PDF/DOCX and submits it to the workspace.
2. The system preserves the exact submitted text or original-document reference as an immutable submission version. It records extraction status and any extracted or normalized text as derived processing data associated with that version and analysis run. If it cannot extract usable text, it reports that limitation and does not claim to have completed content checks.
3. The system identifies candidate claims for that version, searches eligible approved evidence, and applies configured deterministic policy checks. Evidence with unknown freshness may be eligible under §12, but the unknown freshness is disclosed with its source context.
4. The system presents findings with affected text, explanation, evidence/policy references and validity/freshness context where available, and clearly labelled suggestions.
5. The creator may revise and resubmit before review, creating a new immutable version and a separate analysis result while preserving the prior source version and its derived results.

### C. Human review and resolution

1. An authorised reviewer opens the submission and examines the content, findings, linked source records, and applicable policy versions.
2. The reviewer may record one of four decisions: **Changes requested**, **Approved**, **Approved with documented exceptions**, or **Rejected**. The reviewer records a rationale for Rejected and Changes requested decisions. Unresolved findings do not become safe or disappear when a reviewer approves. Approval with exceptions records the human decision and the unresolved findings; it does not change their evidence or policy status. Each unresolved finding requires a disposition and rationale. An authorised reviewer may record a finding disposition and rationale; this does not rewrite source policy or evidence.
3. If changes are requested, the creator edits and submits a new version. The new version receives a new analysis and review cycle linked to the prior version.
4. **Approved** records that no findings remain unresolved for that specific content version. **Approved with documented exceptions** records the evidence/policy basis available at decision time plus a disposition and rationale for each unresolved finding; those findings remain visibly unresolved. Neither outcome publishes the content or guarantees its factual or legal correctness.
5. Rejection closes that review cycle. A later attempt must be a new version or submission and remains linked to the history.

### D. Governance learning

1. The system aggregates recorded findings and decisions for the workspace.
2. An authorised user views basic issue counts/trends and their date range and available-data context.
3. Users may use those signals to discuss process or policy changes. An authorised person must make and record any official policy change separately.

## 11. Roles and permission requirements

The following are minimum MVP permissions. An organisation administrator may also hold another functional role; multi-role account behaviour is **OPEN**.

| Capability | Creator | Brand manager | Evidence/product owner | Compliance reviewer | Organisation administrator |
|---|---:|---:|---:|---:|---:|
| Submit and view own content | Yes | Yes | Yes | Yes | Yes |
| View workspace submissions/findings | Own submissions; shared-review visibility OPEN | Yes | Yes, for evidence work | Yes | Yes |
| Manage policy records | No | Yes | No | No; may comment | Yes |
| Manage evidence records | No | No | Yes | No; may flag | Yes |
| Approve/reject/request changes | No | If assigned reviewer (OPEN) | No | Yes | Administrative override policy OPEN |
| Manage members and roles | No | No | No | No | Yes |
| View governance insights | Basic personal history OPEN | Yes | Yes | Yes | Yes |

- **FR-027 — MUST (MVP):** The system shall enforce role permissions for evidence, policy, member, submission, review, and insight actions.
- **FR-028 — MUST (MVP):** The system shall show users only the submission details permitted by their workspace role and the organisation’s access settings.
- **FR-029 — MUST (MVP):** The system shall record permission-sensitive actions and identify the acting user.

The precise visibility of drafts, whether creators can see other creators’ submissions, whether brand managers can decide reviews, and whether administrators can override a review are **OPEN** decisions.

## 12. Evidence lifecycle and business rules

An evidence record is an organisation-managed source that may be considered during claim review. Minimum fields are: record identifier, title, source reference or file, owner, primary lifecycle state, independent conditions, creation/change history, and optional effective/expiry dates. Evidence scope, claim/category tags, and verification date are desirable but their MVP requirement is **OPEN**.

### Primary lifecycle states

- **Uploaded:** source or reference is registered. Uploading does not imply inspection or approval; Uploaded evidence is not eligible as approved support.
- **Reviewed:** an authorised evidence owner has recorded that the source was inspected. Reviewed evidence is not eligible as approved support until it is explicitly approved.
- **Approved:** an authorised evidence owner or administrator has explicitly approved the reviewed source. Approved evidence is eligible as support unless a supplied validity bound blocks it or it has an Inactive or Conflict-flagged condition. Missing validity information alone does not block eligibility; freshness must be disclosed as unknown.

### Independent evidence conditions

- **Inactive:** an authorised person has withdrawn the source from current use. Setting or clearing this condition changes only the independent Inactive condition and never replaces or changes the primary lifecycle state. While set, the source is ineligible as support; the reason and history remain visible. The authority for clearing this condition is **OPEN**.
- **Expired:** a supplied evidence validity end date has passed at the relevant analysis time. It is ineligible as current support until validity is updated and the evidence is explicitly re-approved. Updating validity creates a revised evidence version; the revised version is ineligible until explicit re-approval. The primary lifecycle state assigned to a revised evidence version after a validity change is **OPEN**. If a supplied effective date is in the future, the evidence is not yet valid and is ineligible for that analysis. Expiry and future-effective ineligibility are determined from supplied validity dates and analysis time, not by replacing the primary lifecycle state.
- **Conflict-flagged:** an authorised person has manually recorded an unresolved known or suspected conflict. The source remains visible for review but is ineligible as support until the flag is cleared by an authorised person with a recorded rationale.

The primary lifecycle state and conditions are separate. An Approved evidence record may also be Expired, Inactive, and/or Conflict-flagged at the same time. Conditions do not erase the evidence's approval history. Missing validity information is represented as **freshness unknown**, not as Expired. Unknown freshness alone does not make otherwise Approved evidence ineligible; any supplied future effective date or passed expiry date does. The interface and review explanation must disclose unknown freshness. Evidence can be simplified to a single owner-reviewed approval action in MVP; separate multi-person review routing is out of scope.

**Eligibility rule:** evidence is eligible as approved support only when its primary lifecycle state is Approved, no supplied validity bound blocks it at the relevant analysis time, and it is neither Inactive nor Conflict-flagged. A supplied future effective date or passed expiry date blocks eligibility. Missing validity information is freshness unknown and, by itself, does not block otherwise Approved evidence; that uncertainty must be disclosed in the interface and review explanation. Uploaded and Reviewed evidence are always ineligible as approved support. Ineligible evidence may be shown as contextual warnings, clearly distinguished from eligible supporting evidence.

There is no MVP automatic evidence conflict detection. Conflict-reporting and resolution authority details remain subject to the OPEN decisions below.

Business rules:

- Only an authorised evidence owner or administrator may change evidence metadata or transition Uploaded to Reviewed or Reviewed to Approved. Setting or clearing Inactive changes that independent condition only and never changes the primary lifecycle state; who may clear Inactive is **OPEN**. Lifecycle transitions do not clear or overwrite independent conditions. Clearing a Conflict-flag requires an authorised person and a recorded rationale; the precise authority and required supporting detail remain **OPEN**.
- Evidence source or metadata edits, including validity-date changes, create a revised evidence version and shall not alter versions referenced by prior reviews. A revised version whose validity information was updated remains ineligible until explicitly re-approved. The primary lifecycle state assigned to that revised version is **OPEN**.
- Retrieval produces a candidate match, not proof. The reviewer must be able to inspect the source and its metadata.
- If no eligible approved match is found, report the claim as **unverified due to missing eligible approved evidence**.
- If only ineligible evidence is found, report that the material exists but is not current approved support, and show it only as a contextual warning distinct from eligible supporting evidence.
- MVP conflicts are recorded manually by an authorised person. When a conflict flag is recorded, show the involved sources and status and route for human resolution; the system does not search for or detect contradictions automatically. Never select a winner silently.
- If source validity or ownership is absent, state that it is unknown. Missing validity information alone does not block otherwise Approved evidence, but the unknown freshness must be disclosed. Do not infer an owner, verification date, or validity period.
- Evidence removal/retention and whether records can be hard-deleted are **OPEN**; prior review traceability must remain sufficient under the chosen retention rule.

## 13. Policy lifecycle and business rules

A policy record contains at minimum a name, rule text, category, status, and version/change history. MVP policy statuses are **Draft**, **Active**, and **Retired**. Draft and retired policies do not trigger current checks. A review retains the active policy version used at analysis time.

Business rules:

- Only an authorised brand manager or administrator may publish, edit, or retire policies.
- MVP automated policy checks are limited to explicit deterministic rules, such as prohibited or required terminology and configured approved messaging. A broad semantic judgement must not be presented as a deterministic violation.
- Each triggered finding identifies the rule and version that triggered it.
- If configured deterministic rules produce incompatible outcomes, report a policy conflict and send it for authorised human resolution. A user may also manually flag a policy as ambiguous. The MVP does not automatically infer general policy ambiguity; do not silently prioritise or invent precedence.
- A reviewer’s disposition applies to the reviewed content finding only. It does not change policy for future reviews.
- Formal clarification or a changed rule requires an authorised user to update and version the policy. Policy conflict detection beyond explicit deterministic collisions is next-release scope.
- Policy approval workflow, effective dates, policy applicability by channel/market, and conflict-resolution ownership are **OPEN**.

## 14. Claim classification and review requirements

For MVP, a candidate claim is a text segment that appears to make a factual assertion or a promotional/product performance assertion that could reasonably require substantiation. The system shall preserve the original wording and location when available. Claim extraction is assistive and may omit or incorrectly classify content; a reviewer can record a disposition for an irrelevant candidate or a missed claim in review notes. Full claim taxonomy and direct editing of extracted claim spans are **OPEN**.

Minimum MVP finding classes:

- **Supported match found:** one or more eligible Approved evidence candidates are linked; this means a candidate source was found, not that truth is established.
- **Unverified — no eligible approved evidence found:** no suitable evidence meeting the eligibility rule in §12 was retrieved.
- **Potentially outdated:** relevant evidence exists but is Expired or freshness is explicitly past due; ineligible material is contextual, not approved support.
- **Evidence conflict:** an authorised person has manually recorded a conflict flag on one or more sources. MVP does not automatically detect contradictions.
- **Policy finding:** a configured rule was triggered.
- **Policy ambiguity/conflict:** a configured deterministic rule collision or a manually recorded ambiguity is routed for human clarification. General automated ambiguity detection is next-release scope.
- **Analysis limitation:** text could not be extracted or a check could not be completed; state which check is incomplete.

The meaning and wording of the attention level shown with an MVP finding are **OPEN**. It must not imply legal risk scoring or factual probability without a separately defined, explainable basis. Ranked severity is not required for MVP.

## 15. Human review and approval lifecycle

Submission review states and permitted transitions:

| State | Meaning | Permitted next states |
|---|---|---|
| Draft | Creator is preparing content | Submitted |
| Submitted | A version is awaiting or undergoing analysis | In review; Analysis blocked |
| Analysis blocked | Required text extraction/check could not complete | Draft (revise/resubmit); In review (reviewer proceeds with limitation, if permitted — OPEN) |
| In review | Findings are available to an authorised reviewer | Changes requested; Approved; Approved with documented exceptions; Rejected |
| Changes requested | Reviewer requires a revised version | Draft (new version) |
| Approved | Reviewer approved this version with no unresolved findings | Terminal for this version |
| Approved with documented exceptions | Reviewer approved despite unresolved findings, each with disposition and rationale; unresolved status remains visible | Terminal for this version |
| Rejected | Reviewer rejected this version | Terminal for this version |

- **FR-030 — MUST (MVP):** Each review decision shall identify the decision-maker, time, content version, and rationale. A rationale is mandatory for Rejected and Changes requested decisions. Approval with unresolved findings requires a rationale for each unresolved finding.
- **FR-031 — MUST (MVP):** Only authorised reviewers may move an in-review version to Approved, Approved with documented exceptions, Rejected, or Changes requested.
- **FR-032 — MUST (MVP):** A decision applies only to the exact content version reviewed. Any material edit requires a new version and review cycle.
- **FR-033 — MUST (MVP):** The system shall prevent transitions not listed as permitted, except for an explicitly authorised administrative correction recorded in the audit history (**whether correction is allowed is OPEN**).
- **FR-034 — MUST (MVP):** Approval shall not trigger publication, distribution, or external action.

Approval is permitted when findings remain unresolved only as **Approved with documented exceptions**. Every unresolved finding must retain its status and have a reviewer disposition and rationale; it remains flagged in the approved version history and is not represented as safe, substantiated, or policy-compliant by the approval. A reviewer may instead request changes or reject. Unresolved findings without a recorded exception rationale block approval. Whether reviewers can reopen a terminal decision and whether an analysis-blocked version can proceed with a recorded limitation are **OPEN**.

## 16. Governance intelligence requirements

MVP governance intelligence is descriptive aggregation of the platform’s own review records, not a source of policy authority. It includes exactly these five metrics; no predictive score or additional dashboard metric is required:

| MVP metric | Definition and counting rule |
|---|---|
| Submission and review counts | Number of submitted content versions and number of review decisions recorded in the selected period. A resubmitted version counts as another submission; each decision event counts once. |
| Unverified claims | Count of claim instances in submitted versions with an analysis result of no eligible Approved evidence match under §12. A claim in a new version is a new instance. This is not a count of false claims. |
| Recurring policy findings | Count of findings by policy/rule identifier in the selected period; show which policy findings recur. Do not infer a trend if there is only one occurrence. |
| Review decision trends | Counts by decision type (Approved, Approved with documented exceptions, Changes requested, Rejected) over the selected period. |
| Evidence requiring attention | Show separate counts for the primary lifecycle states Uploaded and Reviewed awaiting a decision, and for the independent conditions Expired, Inactive, and Conflict-flagged. Conditions are not mutually exclusive: one record may appear in more than one condition count. Do not present a sum of condition counts as a distinct-record total. Unknown freshness is disclosed on the evidence and review context but is not automatically Expired or ineligible; whether it should be a separate attention count is **OPEN**. |

Counts are based on records visible to the user and the chosen period. They are descriptive, may include multiple versions of the same content, and do not imply coverage beyond VerityAI submissions. The date basis for Unverified claims and Recurring policy findings, and whether Evidence requiring attention counts condition changes during the period or conditions at a point in time, remain **OPEN**. Do not infer a date or state-snapshot rule for these metrics until approved. Existing submission/review count and review decision definitions remain unchanged.

- **FR-035 — MUST (MVP):** The system shall display each of the five governance metrics defined in this section, using the stated event and counting rules.
- **FR-036 — MUST (MVP):** Each metric shall state its time range and that it is based only on recorded VerityAI workspace activity; it shall not imply coverage of unsubmitted organisational content.
- **FR-037 — MUST (MVP):** The system shall show zero or an empty state accurately when there are no matching records; it shall label recurring findings as recurring only when the same policy/rule has at least two recorded findings in the selected period. No configurable statistical threshold is required for MVP.
- **FR-038 — MUST (MVP):** Governance insights may recommend areas for human investigation but shall not modify official policy, evidence, or review outcomes.
- **FR-039 — SHOULD (next):** The system should identify recurring reviewer disagreements and policies frequently requiring clarification, with links to underlying review records and appropriate access control.

Insight visibility, aggregation privacy, and retention periods are **OPEN**. The MVP recurrence threshold is fixed at two findings under FR-037; no configurable or statistical threshold is required.

## 17. AI behaviour, uncertainty and explainability requirements

- **NFR-001 — MUST (MVP):** The system shall never describe an AI confidence score, generated explanation, or retrieval similarity as proof that a claim is factually accurate.
- **NFR-002 — MUST (MVP):** The system shall distinguish extracted candidate claims, retrieved candidate evidence, deterministic policy results, human dispositions, and generated suggestions in the interface and stored review record.
- **NFR-003 — MUST (MVP):** For an evidence-supported finding, the system shall expose the source identity and the passage or reference used when available. If no precise passage is available, it shall say so.
- **NFR-004 — MUST (MVP):** For a policy finding, the system shall expose the exact applicable policy text or rule identifier and version.
- **NFR-005 — MUST (MVP):** When a check fails, is incomplete, or has no result, the system shall say which check was affected and shall not present it as passed.
- **NFR-006 — MUST (MVP):** Generated correction suggestions shall be identified as suggestions, remain editable by the creator, and not be represented as approved content.
- **NFR-007 — MUST (MVP):** The system shall not fabricate sources, citations, policy text, evidence metadata, or human decisions. Where a link cannot be provided, it shall state that no source was found.
- **NFR-008 — MUST (MVP):** Human reviewers shall be able to record a disposition that differs from an automated finding, with a rationale and audit record; doing so shall not erase the original finding.
- **NFR-009 — SHOULD (next):** Analysis records should include the relevant model/rule configuration version and analysis timestamp so that a prior result can be interpreted in context.

## 18. Non-functional requirements

Targets below are product requirements to validate during design; where no target is supplied, the value remains **OPEN** rather than assumed.

- **NFR-010 — MUST (MVP):** The system shall preserve workspace separation for all user-visible and stored product records.
- **NFR-011 — MUST (MVP):** The system shall provide an audit record for evidence/policy changes, membership/role changes, submissions, and review decisions, including actor and timestamp.
- **NFR-012 — MUST (MVP):** The system shall show a clear processing, completion, limitation, or failure state for each submitted content version and its required checks, and shall not silently drop failed analysis. Extraction status and other derived results shall be associated with the relevant version and analysis result, not represented as edits to the submitted source.
- **NFR-013 — MUST (MVP):** The system shall preserve the exact submitted text or a reference to the exact originally uploaded file, its version identity and submission metadata, and a source checksum or equivalent integrity reference. Once created, the submitted source snapshot shall not be overwritten. Derived extracted or normalized text, extraction status and warnings, candidate claims, evidence matches, policy results, findings, suggestions, and analysis-stage results shall remain associated with the exact submission version and relevant analysis run. A subsequent material edit shall create a new version and shall not change the prior source or its derived history.
- **NFR-014 — MUST (MVP):** The system shall provide understandable validation errors for unsupported or unreadable documents. Maximum file size, page count, and processing-time targets are **OPEN**.
- **NFR-015 — SHOULD (next):** The product should meet agreed availability, response-time, recovery, and accessibility targets; the targets and measurement method are **OPEN**.
- **NFR-016 — SHOULD (next):** The product should provide export or deletion workflows consistent with an organisation’s approved retention policy; applicable requirements are **OPEN**.

## 19. Privacy, security and responsible AI requirements

- **NFR-017 — MUST (MVP):** Users shall access organisational content only within their authorised workspace and role permissions.
- **NFR-018 — MUST (MVP):** The product shall explain to users that submitted content and evidence are used to perform the requested review; exact notice, retention, and processing disclosures are **OPEN**.
- **NFR-019 — MUST (MVP):** The product shall not use customer content to train shared models without explicit organisation authorisation. The authorisation mechanism and any related product policy are **OPEN**.
- **NFR-020 — MUST (MVP):** The system shall retain and expose source provenance and review history sufficiently to explain findings and decisions, subject to an explicit retention policy (**OPEN**).
- **NFR-021 — MUST (MVP):** The product shall not claim to provide legal advice, regulatory certification, or guaranteed factual accuracy.
- **NFR-022 — MUST (MVP):** The product shall make clear that AI analysis can be incomplete or mistaken and that human review is required for important decisions.
- **NFR-023 — MUST (MVP):** The system shall not automatically publish, distribute, or externally approve submitted content.

Data residency, encryption requirements, incident response, account authentication, deletion timelines, sensitive-data restrictions, and subprocessors are **OPEN** and require product/security decisions before production use.

## 20. Success metrics and measurable outcomes

No baseline, user research, or target results are asserted in this PRD. Baselines and initial targets must be established during the hackathon evaluation or subsequent product validation.

| Metric | Definition | MVP measurement |
|---|---|---|
| End-to-end review completion | Share of test submissions that reach a recorded human decision | Completed decision records / submitted test versions |
| Evidence traceability coverage | Share of extracted candidate claims with a recorded evidence search result and explicit status | Claims with linked match or explicit no-match/limitation / extracted claims |
| Finding explainability completeness | Share of findings with affected content and required policy/source basis or explicit absence | Findings meeting FR-016 basis fields / all findings |
| Human decision capture | Share of terminal review outcomes with actor, timestamp, version, and rationale status | Complete decision records / terminal outcomes |
| Revision resolution | Share of changes-requested review cycles followed by a new version and decision | Completed revision cycles / changes-requested cycles |
| Governance insight coverage | Whether the product can produce category counts/trends with period and data context | Demonstration against seeded, labelled review records |

Targets for each metric, evaluation sample size, and definition of a successful review quality outcome are **OPEN**. These measures indicate workflow completeness and traceability; they do not alone establish factual accuracy or customer value.

## 21. Acceptance criteria for MVP capabilities

- **AC-001:** Given a workspace member with a creator role, when they submit pasted text, then the system preserves the exact text as an immutable version associated with that member, workspace, submission time, and source integrity reference.
- **AC-002:** Given an uploaded PDF or DOCX with extractable text, when analysis completes, then the system associates extracted/normalized text, extraction status, and findings with the exact submitted version and relevant analysis result without altering the original file reference or integrity reference. Given unreadable or unsupported content, it reports the limitation and does not claim checks passed.
- **AC-003:** Given a candidate factual claim and a matching eligible Approved evidence record, when analysis completes, then the finding links to that record and shows its known owner and validity/condition context, or explicitly discloses unknown freshness, while making clear the match is not proof of truth.
- **AC-004:** Given no eligible Approved evidence match, when analysis completes, then the system marks the claim unverified due to missing eligible approved evidence and does not label it false solely for that reason.
- **AC-005:** Given relevant evidence that is Expired, Inactive, or Conflict-flagged, or has a supplied future effective date, when analysis completes, then each applicable condition or date-based eligibility restriction is identified, the evidence is excluded from eligible approved support, and any contextual warning is distinguished from eligible supporting evidence. Multiple conditions may apply to the same record. Setting or clearing Inactive does not change the primary lifecycle state. Given Approved evidence with missing validity information and no other blocking condition, it remains eligible and the interface/review explanation discloses freshness as unknown.
- **AC-006:** Given a configured deterministic terminology rule that is triggered, when analysis completes, then the finding identifies the affected text and exact active policy/rule version.
- **AC-007:** Given a generated correction suggestion, when it is shown, then it is labelled as a suggestion and is not recorded as a verified fact or policy.
- **AC-008:** Given a user without permission to edit policies or evidence, when they attempt the corresponding action, then the system denies the action and records the attempt if it is a material security event under the product audit policy (**audit scope OPEN**).
- **AC-009:** Given an authorised reviewer and an in-review submission, when they record Changes requested, Approved, Approved with documented exceptions, or Rejected, then the system records the actor, timestamp, version, decision, and required rationale and applies the defined state transition.
- **AC-010:** Given changes are requested, when the creator submits a revision, then it is stored as a new immutable source version and the prior submitted content, integrity reference, derived analysis results, findings, and decision remain unchanged and accessible according to permissions.
- **AC-011:** Given an approved submission, then no publication or distribution action occurs as a consequence of approval.
- **AC-012:** Given review records in a selected period, when a user views governance insights, then counts/trends include period and data context and do not imply coverage beyond recorded reviews.
- **AC-013:** Given an ambiguous or conflicting policy basis, when a check cannot determine a consistent outcome, then the system surfaces the ambiguity and routes it for human resolution without silently choosing precedence.
- **AC-014:** Given an authorised person manually flags a conflict between evidence records, then the system shows the Conflict-flagged condition and involved sources, excludes them from eligible approved support, preserves any other conditions on the same records, and does not claim to have detected the conflict automatically.
- **AC-015:** Given an authorised user changes an evidence record or policy, when the change is saved, then the system records actor, timestamp, and a version/history adequate to interpret prior reviews. Evidence source or metadata changes create a revised evidence version without changing versions already referenced by prior reviews.
- **AC-016:** Given evidence is uploaded, then its primary lifecycle is Uploaded and it is excluded from eligible approved support until an authorised user records review and explicit approval. Its independent conditions, if any, do not replace that lifecycle state.
- **AC-017:** Given a supplied evidence validity end date has passed at the relevant analysis time, then the evidence has the Expired condition and is excluded as current approved support; a supplied future effective date also makes it currently ineligible. Missing validity information is represented as freshness unknown, is not treated as Expired, and alone does not exclude otherwise Approved evidence; the unknown freshness is disclosed. After validity is updated, the revised evidence version remains ineligible until explicitly re-approved, while prior versions and review references remain unchanged. The exact primary lifecycle state of the revised version is **OPEN**. Expired remains represented in the Expired evidence-attention category; independent conditions do not replace or erase the primary lifecycle or approval history.
- **AC-018:** Given an in-review version has unresolved findings, when a reviewer approves it, then each unresolved finding must have a recorded disposition and rationale, the version is labelled Approved with documented exceptions, and the unresolved status remains visible.
- **AC-019:** Given an in-review version has any unresolved finding without an exception rationale, when a reviewer attempts approval, then approval is blocked and the reviewer may request changes or reject.
- **AC-020:** Given workspace activity in a selected period, then governance insights show submission and review counts, unverified claim count, recurring policy finding counts, review decision counts by type, and evidence requiring attention according to §16. Evidence attention separates primary lifecycle counts from condition counts; a record may appear in multiple condition counts, which are not represented as mutually exclusive or as a distinct-record total. OPEN metric date/state semantics remain unresolved as stated in §16.
- **AC-021:** Given no matching records for a metric or fewer than two occurrences of a policy finding, then the system shows zero/empty as appropriate and does not label the policy finding recurring.
- **AC-022:** Given two organisation workspaces, when a member of one attempts to access the other workspace's records, then access is denied; within a workspace, each submission is associated with its submitter, workspace, submission time, and review status.
- **AC-023:** Given an administrator adds, deactivates, or changes a member's role, then the updated membership and actor/time are recorded and the applicable role permissions are enforced.
- **AC-024:** Given a finding is presented, then it includes its category, affected content, explanation, and applicable source or policy reference, or explicitly states that no basis was found; any severity label used has a defined meaning and does not claim legal or factual risk.
- **AC-025:** Given a policy is Draft or Retired, then it is not applied to new checks; given a policy is changed or retired, then the active version and prior review snapshots remain distinguishable.
- **AC-026:** Given a submitted version is analysed, then candidate claims, candidate evidence, deterministic policy results, human dispositions, generated suggestions, and analysis-stage outcomes are associated with that exact version and relevant analysis result, separately from the immutable submitted source. Incomplete checks are identified as incomplete and no confidence or similarity score is described as proof.
- **AC-027:** Given a reviewer disposition differs from an automated finding, then both the original finding and the human disposition with rationale, actor, and time remain in the review history.
- **AC-028:** Given a creator or reviewer views a generated correction, then it is labelled as a suggestion, can be edited by the creator, and is not recorded as a verified fact or approved policy.
- **AC-029:** Given a user accesses a submission, evidence record, or policy, then workspace and role access rules are enforced; the system presents the review-purpose notice defined by the product and does not claim legal advice, certification, or guaranteed accuracy.
- **AC-030:** Given any evidence, policy, role, submission, or review decision change, then the audit history identifies the actor and time; prior content and source/policy versions referenced by completed reviews remain explainable.
- **AC-031:** Given customer content is submitted, then it is used for the requested review and is not used to train a shared model unless the organisation has explicitly authorised that use under a defined product policy.

### MVP acceptance coverage

All MVP **MUST** functional requirements (FR-001–FR-017, FR-020–FR-024, FR-027–FR-038) and MVP **MUST** non-functional requirements (NFR-001–NFR-008, NFR-010–NFR-014, NFR-017–NFR-023) map to one or more acceptance criteria above. In particular, governance metrics are covered by AC-020 and AC-021; evidence lifecycle and manually recorded conflicts by AC-003–AC-005 and AC-014–AC-017; approval exceptions by AC-009 and AC-018–AC-019. FR-018, FR-019, FR-025, FR-026, NFR-009, NFR-015, and NFR-016 are next-release or future requirements and are not MVP acceptance gates.

## 22. Risks, assumptions and dependencies

### Assumptions to validate

- The product is industry-agnostic; a fictional fintech organisation may be used to demonstrate it.
- English is the initial language.
- MVP input includes pasted text and PDF/DOCX documents; successful analysis depends on extractable text.
- Human approval remains mandatory for important decisions.
- The platform does not publish content automatically and does not provide legal or regulatory certification.
- Organisations can designate authorised owners for evidence and policies.
- Basic role-based permissions and review records are sufficient to demonstrate Round 2; detailed access rules remain to be confirmed.

### Risks

- Poorly maintained, incomplete, or conflicting sources may produce weak matches or require substantial human work.
- Claim extraction and semantic retrieval can miss claims or return irrelevant candidates; the interface must make these limitations visible.
- Ambiguous policy language can create inconsistent findings; deterministic MVP checks must remain narrow and traceable.
- Document parsing failures can leave content partially reviewed; analysis status must identify incomplete checks.
- A reviewer may over-trust automated results; wording and workflow must clearly distinguish matches, suggestions, and human decisions.
- Governance insights from small or biased samples may mislead; data context and threshold decisions are needed.
- Retention, data handling, and access rules are not yet fully specified and may affect production readiness.

### Dependencies

- Organisation-provided guideline and evidence records with sufficient metadata for review.
- Users assigned to workspace roles and available human reviewers.
- A defined MVP policy set for deterministic checks and a labelled demonstration dataset, if used.
- Text extraction capability for supported PDF/DOCX input; OCR is not an MVP requirement.
- Product/security decisions on data handling, retention, access visibility, and authentication before real organisational data is used.

## 23. Explicit out-of-scope items

- Automatic publication, distribution, or external approval of content.
- Treating an LLM, similarity score, or confidence score as an authoritative source of truth.
- Declaring a claim false solely because evidence was not found.
- Fabricating or silently inferring evidence, sources, policies, owners, dates, or policy precedence.
- Legal advice, regulatory certification, or guaranteed compliance/factual correctness.
- Automatic changes to official policy or evidence based on insights or AI recommendations.
- Advanced image/visual analysis, multilingual operation, CMS integrations, or continuous published-content monitoring in MVP.
- Selecting architecture, frameworks, databases, AI vendors, or deployment platforms in this PRD.
- Detailed implementation plans, source code, or engineering task breakdowns.

## 24. Open product questions requiring decisions

1. **OPEN:** Who is the named product owner and who approves product requirement changes?
2. **OPEN:** Can one user hold multiple roles, and what are the exact visibility rules for drafts and submissions from other creators?
3. **OPEN:** May brand managers act as reviewers? May administrators correct or override a decision, or may reviewers reopen a terminal decision, and how must any such action be audited?
4. **OPEN:** Which content is considered “important” and therefore requires mandatory human approval? Is all MVP content treated this way?
5. **OPEN:** What evidence metadata beyond title, source/reference, owner, and optional validity dates is mandatory in MVP?
6. **OPEN:** What rationale or supporting detail is required when an authorised person manually flags or clears an evidence conflict, and who is assigned to resolve it?
7. **OPEN:** What policy categories and deterministic rule types will the demonstration support? How are applicability, precedence, effective dates, policy approval, and conflict-resolution ownership represented?
8. **OPEN:** What meaning and wording should the required MVP finding attention level use, without implying regulatory or factual risk scores? Ranked severity is not required.
9. **OPEN:** Can users edit, dismiss, or reclassify extracted claim candidates and findings in MVP? What rationale is required?
10. **OPEN:** If document extraction or a required check fails, can an authorised reviewer proceed with a recorded limitation, or must the creator resubmit?
11. **OPEN:** Which roles may view governance metrics and underlying records?
12. **OPEN:** What retention, deletion, export, data residency, encryption, authentication, audit-event scope, and customer-content handling policies apply?
13. **OPEN:** What maximum document size/page count, processing-time expectation, availability target, and accessibility target are appropriate?
14. **OPEN:** What measurable MVP targets, evaluation sample size, and definition of a successful review quality outcome establish acceptable workflow completeness and usefulness?
15. **OPEN:** For Unverified claims and Recurring policy findings, which event date determines inclusion in a selected period? For Evidence requiring attention, should counts reflect condition changes during the period or conditions at a point in time?
16. **OPEN:** Who may clear the independent Inactive condition, and what primary lifecycle state applies to a revised evidence version after validity information is changed and before explicit re-approval?
17. **OPEN:** Should evidence with unknown freshness have a separate Evidence requiring attention count? It is not automatically Expired or ineligible under §12.
