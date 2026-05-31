package com.cobolmodernizer.cobol.json;

/** v2 DataItem node: WORKING-STORAGE / LINKAGE items and copybook fields.
 *  Lives in the graph; NEVER materialized into prompts (master-plan §4.2). */
public record DataItemJson(
    String kind,            // always "DataItem"
    String qualifiedName,   // PROG.ITEM-NAME
    String simpleName,
    String filePath,
    int startLine,
    int endLine,
    boolean isExternal,
    int level,              // COBOL level number (01/05/10/...)
    String picture,         // PIC clause text or null
    String usage,           // COMP-3 | DISPLAY | ... | null
    String redefines,       // REDEFINES target simpleName or null
    int occurs,             // OCCURS count, 0 if none
    String parentQname      // group parent qualifiedName or null
) {}
