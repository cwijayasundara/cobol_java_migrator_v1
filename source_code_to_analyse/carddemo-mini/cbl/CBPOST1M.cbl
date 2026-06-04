       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBPOST1M.
       AUTHOR. AWS-MINI.
      *****************************************************************
      * Mini posting program, derived from CardDemo CBTRN02C.
      * Reads daily transactions, validates each amount (CALL CBVALDTM),
      * adds it to the account balance and REWRITEs ACCTFILE, then
      * WRITEs the posted transaction to TRANFILE.
      * This is a WRITER seam (REWRITE ACCTFILE + WRITE TRANFILE).
      *****************************************************************
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT DALYTRAN-FILE ASSIGN TO DALYTRAN
                  ORGANIZATION IS SEQUENTIAL
                  FILE STATUS  IS DALYTRAN-STATUS.
           SELECT ACCTFILE-FILE ASSIGN TO ACCTFILE
                  ORGANIZATION IS INDEXED
                  ACCESS MODE  IS RANDOM
                  RECORD KEY   IS FD-ACCT-ID
                  FILE STATUS  IS ACCTFILE-STATUS.
           SELECT TRANFILE-FILE ASSIGN TO TRANFILE
                  ORGANIZATION IS SEQUENTIAL
                  FILE STATUS  IS TRANFILE-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  DALYTRAN-FILE.
       01  DALYTRAN-REC.
           05  DT-ACCT-ID              PIC 9(11).
           05  DT-AMOUNT               PIC S9(10)V99.
       FD  ACCTFILE-FILE.
       01  FD-ACCT-REC.
           05  FD-ACCT-ID              PIC 9(11).
           05  FILLER                  PIC X(69).
       FD  TRANFILE-FILE.
       01  TRAN-REC                    PIC X(80).
       WORKING-STORAGE SECTION.
       01  DALYTRAN-STATUS             PIC X(02).
       01  ACCTFILE-STATUS             PIC X(02).
       01  TRANFILE-STATUS             PIC X(02).
       01  END-OF-FILE                 PIC X(01) VALUE 'N'.
       01  WS-VALID-FLAG               PIC X(01).
       COPY CVACT01M.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-OPEN-FILES
           PERFORM 2000-PROCESS-TRAN UNTIL END-OF-FILE = 'Y'
           PERFORM 9000-CLOSE-FILES
           STOP RUN.
       1000-OPEN-FILES.
           OPEN INPUT DALYTRAN-FILE
           OPEN I-O ACCTFILE-FILE
           OPEN OUTPUT TRANFILE-FILE.
       2000-PROCESS-TRAN.
           READ DALYTRAN-FILE
               AT END
                   MOVE 'Y' TO END-OF-FILE
               NOT AT END
                   PERFORM 2100-POST-TRAN
           END-READ.
       2100-POST-TRAN.
           CALL 'CBVALDTM' USING DT-AMOUNT WS-VALID-FLAG
           IF WS-VALID-FLAG = 'Y'
               PERFORM 2200-UPDATE-ACCOUNT
               PERFORM 2300-WRITE-TRAN
           END-IF.
       2200-UPDATE-ACCOUNT.
           MOVE DT-ACCT-ID TO FD-ACCT-ID
           READ ACCTFILE-FILE INTO ACCOUNT-RECORD
           ADD DT-AMOUNT TO ACCT-CURR-BAL
           MOVE ACCOUNT-RECORD TO FD-ACCT-REC
           REWRITE FD-ACCT-REC.
       2300-WRITE-TRAN.
           MOVE DALYTRAN-REC TO TRAN-REC
           WRITE TRAN-REC.
       9000-CLOSE-FILES.
           CLOSE DALYTRAN-FILE ACCTFILE-FILE TRANFILE-FILE.
