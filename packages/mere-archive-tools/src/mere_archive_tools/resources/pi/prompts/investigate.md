Investigate the following question against the local archive:

{{QUESTION}}

Use `archive_search` before you answer. A result list isn't proof that you found
every required fact. Break compound questions into claims. Search again with
specific names, vendors, document types, dates, identifiers, and synonyms when
the first results don't support every claim. Stop after you have enough evidence
or the search budget is exhausted.

Use only facts stated in returned snippets. Cite paths exactly as the tool
returns them. Mark a claim `unresolved` when the searches don't support it. Do
not fill gaps with general knowledge or likely conclusions. Distinguish warranty
coverage for replacement parts from reimbursement of a repair charge. Coverage
of some items doesn't establish that other items are excluded. An invoice line
isn't evidence of reimbursement or a warranty exclusion. Never turn missing
evidence into a negative factual claim. Mark both positive and negative claims
unresolved unless the snippets explicitly support them. Search for each required
document type before concluding that a fact is unresolved.

Return only one JSON object with this shape:

{
  "contractVersion": "mere.run/archive-investigation.v1",
  "answer": "A concise answer that distinguishes supported and unresolved facts.",
  "claims": [
    {
      "id": "claim-1",
      "statement": "One independently verifiable statement.",
      "status": "supported",
      "sources": ["relative/path/from/search.pdf"]
    },
    {
      "id": "claim-2",
      "statement": "A fact that the available search evidence doesn't establish.",
      "status": "unresolved",
      "sources": []
    }
  ]
}
