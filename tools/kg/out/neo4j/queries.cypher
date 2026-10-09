// Competency queries
// 1. Where is a concept anchored?
MATCH (c:Concept {id: 'opaque_payload'})-[:HAS_CODE_EVIDENCE]->(e)
RETURN e.module, e.symbol, e.line, e.quote;
// 2. What does a contract rest on?
MATCH p = (c:Concept {id: 'registration'})-[:USES*1..3]->(d)
RETURN DISTINCT d.id, length(p) AS depth ORDER BY depth;
// 3. Paraphrase plus bibliographic pointers
MATCH (c:Concept {id: 'scheme_dispatch'})
OPTIONAL MATCH (c)-[:DEFINED_IN]->(r)
RETURN c.label, c.definition, collect({src: r.source, url: r.url, status: r.status});
// 4. Concepts with no external citation
MATCH (c:Concept) WHERE NOT (c)-[:DEFINED_IN]->(:Reference)
RETURN c.id, c.label;
// 5. Free-text entry point
CALL db.index.fulltext.queryNodes('concept_text', 'opaque payload')
YIELD node, score RETURN node.id, node.label, score LIMIT 5;
// 6. Contrasts
MATCH (a)-[r:CONTRASTS_WITH]->(b) RETURN a.label, type(r), b.label;
// 7. Everything a file touches
MATCH (c:Concept)-[:HAS_CODE_EVIDENCE]->(e {module: 'src/urisolver/redaction.py'})
RETURN DISTINCT c.id, c.label;
