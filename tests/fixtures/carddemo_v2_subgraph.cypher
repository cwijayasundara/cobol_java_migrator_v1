CREATE (coactvwc:CodeEntity {repo:'cardemo', kind:'Program', simple_name:'COACTVWC',
        qualified_name:'COACTVWC', file_path:'app/cbl/COACTVWC.cbl', is_external:false,
        start_line:1, end_line:940});
CREATE (cbtrn02c:CodeEntity {repo:'cardemo', kind:'Program', simple_name:'CBTRN02C',
        qualified_name:'CBTRN02C', file_path:'app/cbl/CBTRN02C.cbl', is_external:false,
        start_line:1, end_line:600});
CREATE (cbact01c:CodeEntity {repo:'cardemo', kind:'Program', simple_name:'CBACT01C',
        qualified_name:'CBACT01C', file_path:'app/cbl/CBACT01C.cbl', is_external:false,
        start_line:1, end_line:400});
CREATE (acctfile:CodeEntity {repo:'cardemo', kind:'DataItem', simple_name:'ACCTFILE',
        qualified_name:'ACCTFILE', file_path:'', is_external:true});
CREATE (custfile:CodeEntity {repo:'cardemo', kind:'DataItem', simple_name:'CUSTFILE',
        qualified_name:'CUSTFILE', file_path:'', is_external:true});
CREATE (transact:CodeEntity {repo:'cardemo', kind:'DataItem', simple_name:'TRANSACT',
        qualified_name:'TRANSACT', file_path:'', is_external:true});
// COACTVWC reads ACCTFILE + CUSTFILE (CICS, reader-only)
MATCH (p {qualified_name:'COACTVWC'}),(a {qualified_name:'ACCTFILE'})
  CREATE (p)-[:EXECUTES_CICS {resource:'ACCTFILE', command:'READ', intent:'read'}]->(a);
MATCH (p {qualified_name:'COACTVWC'}),(c {qualified_name:'CUSTFILE'})
  CREATE (p)-[:EXECUTES_CICS {resource:'CUSTFILE', command:'READ', intent:'read'}]->(c);
// CBACT01C reads ACCTFILE (batch sequential)
MATCH (p {qualified_name:'CBACT01C'}),(a {qualified_name:'ACCTFILE'})
  CREATE (p)-[:READS {resource:'ACCTFILE', resourceType:'VSAM', mode:'sequential'}]->(a);
// CBTRN02C writes ACCTFILE + TRANSACT (REWRITE -> writer, identity-drift)
MATCH (p {qualified_name:'CBTRN02C'}),(a {qualified_name:'ACCTFILE'})
  CREATE (p)-[:WRITES {resource:'ACCTFILE', resourceType:'VSAM', mode:'random'}]->(a);
MATCH (p {qualified_name:'CBTRN02C'}),(t {qualified_name:'TRANSACT'})
  CREATE (p)-[:WRITES {resource:'TRANSACT', resourceType:'VSAM', mode:'random'}]->(t);
