package com.cobolmodernizer.accountview.domain;

import com.cobolmodernizer.accountview.acl.CobolRecordCodec;
import com.cobolmodernizer.accountview.acl.PackedDecimal;
import com.cobolmodernizer.accountview.api.AccountView;
import com.cobolmodernizer.accountview.repo.CapturedVsamRepository;
import java.math.BigDecimal;
import java.util.Optional;
import org.springframework.stereotype.Service;

/** Read path mirroring COACTVWC 9000-READ-ACCT: xref -> account -> customer.
 *  Required behavior only; no BMS/screen plumbing (accidental legacy behavior). */
@Service
public class AccountViewService {
    private final CapturedVsamRepository repo;

    public AccountViewService(CapturedVsamRepository repo) { this.repo = repo; }

    public AccountView view(String acctId) {
        Optional<byte[]> xref = repo.readXref(acctId);
        if (xref.isEmpty()) return null;
        Optional<byte[]> acct = repo.readAccount(acctId);
        if (acct.isEmpty()) return null;
        // XREF-CUST-ID at offset 16, PIC 9(09) DISPLAY
        String custId = CobolRecordCodec.text(xref.get(), 16, 9);
        Optional<byte[]> cust = repo.readCustomer(custId);
        if (cust.isEmpty()) return null;

        byte[] a = acct.get();
        byte[] c = cust.get();
        // CVACT01Y offsets: ACCT-ID 0..11, STATUS 11..12, CURR-BAL 12.. (COMP-3 6 bytes)
        String status = CobolRecordCodec.text(a, 11, 1);
        BigDecimal balance = PackedDecimal.decode(java.util.Arrays.copyOfRange(a, 12, 18), 2);
        BigDecimal limit   = PackedDecimal.decode(java.util.Arrays.copyOfRange(a, 18, 24), 2);
        // CVCUS01Y offsets: CUST-FIRST-NAME 9..34, CUST-LAST-NAME 59..84, FICO 488..491
        String first = CobolRecordCodec.text(c, 9, 25);
        String last  = CobolRecordCodec.text(c, 59, 25);
        int fico = Integer.parseInt(CobolRecordCodec.text(c, 488, 3).strip());
        return CobolRecordCodec.assemble(acctId, status, balance, limit,
                                         custId, first, last, fico);
    }
}
