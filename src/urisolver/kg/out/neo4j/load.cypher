// urisolver concept knowledge graph -- Neo4j 5 loader
// Copy the CSVs into the import/ directory, then run this file.
CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (e:CodeEvidence) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT reference_id IF NOT EXISTS FOR (r:Reference) REQUIRE r.id IS UNIQUE;
CREATE FULLTEXT INDEX concept_text IF NOT EXISTS FOR (c:Concept) ON EACH [c.label, c.definition, c.aliases];
CREATE FULLTEXT INDEX reference_text IF NOT EXISTS FOR (r:Reference) ON EACH [r.title, r.quote];

LOAD CSV WITH HEADERS FROM 'file:///concepts.csv' AS row
MERGE (c:Concept {id: row.`id:ID(Concept)`})
SET c.label = row.label, c.kind = row.kind, c.definition = row.definition,
    c.aliases = [a IN split(row.aliases, ';') WHERE a <> ''],
    c.literature = [l IN split(row.literature, ';') WHERE l <> ''];

LOAD CSV WITH HEADERS FROM 'file:///code_evidence.csv' AS row
MERGE (e:CodeEvidence {id: row.`id:ID(Evidence)`})
SET e.module = row.module, e.symbol = row.symbol, e.symbol_kind = row.symbol_kind,
    e.line = toInteger(row.`line:int`), e.quote = row.quote, e.uri = row.uri,
    e.sha256 = row.sha256;

LOAD CSV WITH HEADERS FROM 'file:///code_evidence_edges.csv' AS row
MATCH (c:Concept {id: row.`:START_ID(Concept)`}), (e:CodeEvidence {id: row.`:END_ID(Evidence)`})
MERGE (c)-[:HAS_CODE_EVIDENCE]->(e);

LOAD CSV WITH HEADERS FROM 'file:///references.csv' AS row
MERGE (r:Reference {id: row.`id:ID(Reference)`})
SET r.source = row.source, r.title = row.title, r.page_title = row.page_title,
    r.url = row.url, r.status = row.status, r.quote = row.quote,
    r.note = row.note, r.fetched = row.fetched
WITH r, row
CALL { WITH r, row WITH r, row WHERE row.source = 'literature' SET r:Literature }
RETURN count(r);

LOAD CSV WITH HEADERS FROM 'file:///reference_edges.csv' AS row
MATCH (c:Concept {id: row.`:START_ID(Concept)`}), (r:Reference {id: row.`:END_ID(Reference)`})
MERGE (c)-[d:DEFINED_IN]->(r) SET d.receipt = row.receipt;

LOAD CSV WITH HEADERS FROM 'file:///concept_relations.csv' AS row
MATCH (a:Concept {id: row.`:START_ID(Concept)`}), (b:Concept {id: row.`:END_ID(Concept)`})
CALL apoc.merge.relationship(a, row.`:TYPE`, {}, {receipt: row.receipt}, b, {}) YIELD rel
RETURN count(rel);
// Without APOC, replace the last statement by one MERGE per type, e.g.
// MATCH ... WHERE row.`:TYPE` = 'USES' MERGE (a)-[:USES {receipt: row.receipt}]->(b);
