       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBACT01M.
       AUTHOR. AWS-MINI.
      *****************************************************************
      * Mini account-file reader, derived from CardDemo CBACT01C.
      * Reads ACCTFILE sequentially and displays each account.
      * This is a READER-ONLY seam (no file writes).
      *****************************************************************
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCTFILE-FILE ASSIGN TO ACCTFILE
                  ORGANIZATION IS INDEXED
                  ACCESS MODE  IS SEQUENTIAL
                  RECORD KEY   IS FD-ACCT-ID
                  FILE STATUS  IS ACCTFILE-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  ACCTFILE-FILE.
       01  FD-ACCT-REC.
           05  FD-ACCT-ID              PIC 9(11).
           05  FILLER                  PIC X(69).
       WORKING-STORAGE SECTION.
       01  ACCTFILE-STATUS             PIC X(02).
       01  END-OF-FILE                 PIC X(01) VALUE 'N'.
       COPY CVACT01M.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-OPEN-FILE
           PERFORM 2000-READ-NEXT UNTIL END-OF-FILE = 'Y'
           PERFORM 9000-CLOSE-FILE
           STOP RUN.
       1000-OPEN-FILE.
           OPEN INPUT ACCTFILE-FILE.
       2000-READ-NEXT.
           READ ACCTFILE-FILE INTO ACCOUNT-RECORD
               AT END
                   MOVE 'Y' TO END-OF-FILE
               NOT AT END
                   PERFORM 2100-DISPLAY-ACCT
           END-READ.
       2100-DISPLAY-ACCT.
           DISPLAY 'ACCT ' ACCT-ID ' BAL ' ACCT-CURR-BAL.
       9000-CLOSE-FILE.
           CLOSE ACCTFILE-FILE.
