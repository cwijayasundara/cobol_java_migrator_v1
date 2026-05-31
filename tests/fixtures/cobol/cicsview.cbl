       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSVIEW.
       PROCEDURE DIVISION.
       0000-MAIN.
           EXEC CICS RECEIVE MAP('CACTVWA')
                MAPSET('COACTVW') END-EXEC.
           EXEC CICS READ
                DATASET   (LIT-ACCTFILENAME)
                RIDFLD    (WS-CARD-RID-ACCT-ID-X)
                INTO      (ACCOUNT-RECORD)
           END-EXEC.
           EXEC CICS REWRITE
                DATASET   (LIT-ACCTFILENAME)
                FROM      (ACCOUNT-RECORD)
           END-EXEC.
           EXEC CICS SEND MAP('CACTVWA')
                MAPSET('COACTVW') END-EXEC.
           EXEC CICS RETURN END-EXEC.
