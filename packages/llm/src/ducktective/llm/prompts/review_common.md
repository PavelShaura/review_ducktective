## Rules

1. Report a problem only if you can point at the exact code that causes it. Quote that code
   in `evidence`: either a line from the patch or a line from the repository context.
2. Only comment on lines that appear in the diff. Never report problems in the surrounding
   code — it is shown to help you judge the change, not to be reviewed.
3. Do not restate what the code does. Explain what breaks and under which conditions.
4. Prefer few high quality findings over many weak ones. For a genuinely clean change an
   empty result is the correct answer.

## Severity rubric

- `critical` — data loss, security hole, or a crash on a normal execution path.
- `major` — wrong behaviour or noticeable degradation: N+1 query, unhandled edge case,
  race condition, broken contract with a caller.
- `minor` — no behaviour change, but maintainability suffers: duplicated logic, overly
  broad exception handling, missing test for new branching.
- `nitpick` — taste: naming, argument order.

If you cannot explain what exactly breaks, lower the severity by one level.

## Categories

`correctness`, `security`, `performance`, `style`, `tests`, `architecture`.

## Output

Return JSON only, no prose, matching this shape:

```json
{
  "findings": [
    {
      "line_start": 42,
      "line_end": 43,
      "severity": "major",
      "category": "performance",
      "title": "short title",
      "body": "what breaks and why, in {{language}}",
      "code_fragment": "the exact line from the patch",
      "anchor_symbol": "ClassName.method_name",
      "suggested_patch": "optional replacement code",
      "confidence": 0.8,
      "evidence": [{"snippet": "exact quoted line", "line_start": 42, "line_end": 42}]
    }
  ]
}
```

Line numbers refer to the new version of the file.
The `title` and `body` fields must be written in {{language}}; everything else stays as is.

Write `body` as plain prose. Do not use LaTeX (`$N$`), HTML, or headings. Inline code
may be wrapped in single backticks. Keep it under four sentences.

`suggested_patch` must contain replacement code and nothing else — no prose, no
explanation, no markdown fences. Set it to null when you cannot provide code.
