# AGENTS.md

Before describing a urisolver contract, tier, scheme, or resolver behavior, query the
concept graph. Do not invent behavior that the card does not show.

```bash
python -m urisolver.kg search "opaque payload"
python -m urisolver.kg card tier_0
python -m urisolver.kg module src/urisolver/redaction.py
python -m urisolver.kg receipt ent:concept:tier_0
```

`definition` is a paraphrase (`definition_receipt`). A `code_evidence` quote is a
verbatim sentence from `DESIGN.md`, `SCHEMES.md`, or a docstring, hashed with the
file. On a receipt, `how=quote` is that sentence, `how=derived` is the paraphrase
or a bibliographic pointer, and `how=inferred` is a relation the builder asserted.
