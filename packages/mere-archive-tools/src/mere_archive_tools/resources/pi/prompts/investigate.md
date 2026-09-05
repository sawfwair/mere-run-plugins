Investigate the following question against the local archive:

{{QUESTION}}

Use `archive_search` before you answer. A result list isn't proof that you found
every required fact. Break compound questions into claims. Search again with
specific names, vendors, document types, dates, identifiers, and synonyms when
the first results don't support every claim. Stop after you have enough evidence
or the search budget is exhausted.

Use only facts stated in returned snippets. Cite paths exactly as the tool
returns them. Mark a claim `unresolved` when the searches don't support it. Do
not fill gaps with general knowledge or likely conclusions.

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
