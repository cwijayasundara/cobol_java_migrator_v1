       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBVALDTM.
       AUTHOR. AWS-MINI.
      *****************************************************************
      * Mini validation subprogram called by CBPOST1M. Sets the flag
      * to 'Y' when the transaction amount is within the allowed range.
      *****************************************************************
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MAX-AMOUNT               PIC S9(10)V99 VALUE 9999999.99.
       LINKAGE SECTION.
       01  LK-AMOUNT                   PIC S9(10)V99.
       01  LK-VALID-FLAG               PIC X(01).
       PROCEDURE DIVISION USING LK-AMOUNT LK-VALID-FLAG.
       0000-VALIDATE.
           IF LK-AMOUNT > 0 AND LK-AMOUNT <= WS-MAX-AMOUNT
               MOVE 'Y' TO LK-VALID-FLAG
           ELSE
               MOVE 'N' TO LK-VALID-FLAG
           END-IF
           GOBACK.
