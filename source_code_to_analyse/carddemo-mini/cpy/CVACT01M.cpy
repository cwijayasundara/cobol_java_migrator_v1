      *****************************************************************
      *    Mini account record (RECLN 80) derived from CardDemo
      *    CVACT01Y (ACCOUNT-RECORD, RECLN 300) — trimmed for a small,
      *    self-contained example.
      *****************************************************************
       01  ACCOUNT-RECORD.
           05  ACCT-ID                 PIC 9(11).
           05  ACCT-ACTIVE-STATUS      PIC X(01).
           05  ACCT-CURR-BAL           PIC S9(10)V99.
           05  ACCT-CREDIT-LIMIT       PIC S9(10)V99.
           05  FILLER                  PIC X(44).
