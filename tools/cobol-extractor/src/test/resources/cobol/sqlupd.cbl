       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLUPD.
       PROCEDURE DIVISION.
       0000-MAIN.
           EXEC SQL
                SELECT COUNT(1)
                  INTO :WS-RECORDS-COUNT
                  FROM CARDDEMO.TRANSACTION_TYPE
           END-EXEC.
           EXEC SQL
                UPDATE CARDDEMO.TRANSACTION_TYPE
                   SET TR_DESCRIPTION = :DCL-TR-DESC
                 WHERE TR_TYPE = :DCL-TR-TYPE
           END-EXEC.
