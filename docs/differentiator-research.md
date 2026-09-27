# Adaptive Diagnostic Probe: Industry Pattern and Project Gap

## Existing industry pattern

ServiceNow's Troubleshooting Steps Identification AI Agent reads case context, attempted steps, similar cases, knowledge articles, and SOPs, then proposes additional troubleshooting steps. Microsoft Dynamics 365 uses intent attributes to suggest information gathering questions during a service conversation and provides next-best actions in a case workflow. Both demonstrate that support systems are moving from answer retrieval toward context-aware guided actions.

Research on Diagnostic Question Answering for IT Support also argues for maintaining competing diagnostic hypotheses and selecting the next question or investigation from accumulated evidence. Its evaluation is research evidence for that design direction, not a claim about this repository's expected performance.

## Gap

The industry products have broad case and conversation context, but they are configured against each organization's intent, case, and knowledge sources. This project has a much smaller but unusually constrained knowledge base: the provided SIIS text is authoritative, the public response schema is fixed, and deeplinks are a masked catalog. A useful hackathon distinction is therefore a probe chooser that is explicitly limited to source-authored checks and validated against that catalog. It does not invent a question to sound diagnostic.

## Our differentiator

On a short, underspecified complaint, or when distinct SIIS articles have close retrieval scores, the engine can start with a low-risk observation/check already present in the leading SIIS procedure. Duplicate rows for the same article are collapsed before this ambiguity check. A simple, inspectable branch-separation heuristic scores candidate checks; this is not calibrated information gain. The returned first action contains one exact source sentence. Internal response metadata records candidate SIIS sources, matching signals, the selected source-backed probe, and its score. Destructive actions are excluded from probe candidates. No probabilistic root-cause diagnosis or extra LLM call is used.

The score is a lightweight ranking heuristic, not a calibrated probability or measured diagnostic accuracy. Because the schema has no question field, the feature emits an existing check/action rather than adding a new response field or fabricating a question. The current asset set has no multi-turn diagnostic-state API, so this implementation is single-turn.

## Why it matters

A long generic checklist can ask the customer to try fixes for competing causes before establishing what is happening. A grounded, low-risk check lets the flow gather one useful observation first, while the SIIS text and existing schema keep the response auditable.

## Demo scenario

1. Submit `my screen keeps going black` to a cold engine.
2. Show the public plan starts with the SIIS-authored physical/liquid-damage inspection sentence, rather than returning the full list immediately.
3. Show the diagnostics explain that this short query selected a source-backed check, with no invented question or link.
4. Submit `the screen flashes only when I open Gmail` and show the engine withholding a mismatched Camera troubleshooting article when the SIIS content does not support the app-specific trigger.

## Sources

- [ServiceNow: Troubleshooting steps identification AI agent](https://www.servicenow.com/docs/r/customer-service-management/now-assist-for-csm/troubleshooting-steps-identification-ai-agent.html)
- [Microsoft Learn: Enable intent-based suggestions for service representatives](https://learn.microsoft.com/en-us/dynamics365/contact-center/administer/enable-intent-for-service-reps)
- [Microsoft Learn: View next best actions with Customer Intent Agent](https://learn.microsoft.com/en-us/dynamics365/release-plan/2026wave1/service/dynamics365-customer-service/view-next-best-actions-customer-intent-agent)
- [Kapoor et al., Diagnostic Question Answering for IT Support (2026)](https://arxiv.org/abs/2604.05350)
