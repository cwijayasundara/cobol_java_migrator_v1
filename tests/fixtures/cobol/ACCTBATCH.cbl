       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTBATCH.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE  ASSIGN TO "ACCTIN"
                  ORGANIZATION IS LINE SEQUENTIAL.
           SELECT OUT-FILE ASSIGN TO "ACCTOUT"
                  ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-ACCT-ID    PIC 9(11).
           05  IN-CURR-BAL   PIC S9(10)V99.
       FD  OUT-FILE.
       01  OUT-REC.
           05  OUT-ACCT-ID   PIC 9(11).
           05  OUT-NEW-BAL   PIC S9(10)V99.
       WORKING-STORAGE SECTION.
       01  WS-EOF            PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE OUTPUT OUT-FILE
           PERFORM UNTIL WS-EOF = 'Y'
               READ IN-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       MOVE IN-ACCT-ID TO OUT-ACCT-ID
                       COMPUTE OUT-NEW-BAL = IN-CURR-BAL + 0.01
                       WRITE OUT-REC
               END-READ
           END-PERFORM
           CLOSE IN-FILE OUT-FILE
           DISPLAY 'ACCTBATCH DONE'
           GOBACK.
