package com.cobolmodernizer.accountview.acl;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.cobolmodernizer.accountview.api.AccountView;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

class CobolRecordCodecTest {

    @Test
    void decodesAccountIdAndStatusFromDisplayFields() {
        // 11-digit acct id "00000000123", status "Y"
        byte[] rec = ("00000000123" + "Y").getBytes(StandardCharsets.US_ASCII);
        String acctId = CobolRecordCodec.text(rec, 0, 11).strip();
        String status = CobolRecordCodec.text(rec, 11, 1);
        assertEquals("00000000123", acctId);
        assertEquals("Y", status);
    }

    @Test
    void assemblesAccountViewFromThreeRecords() {
        AccountView v = CobolRecordCodec.assemble(
            /*acctId*/ "00000000123",
            /*status*/ "Y",
            /*balance*/ new java.math.BigDecimal("1234.56"),
            /*creditLimit*/ new java.math.BigDecimal("5000.00"),
            /*custId*/ "000000042",
            /*firstName*/ "JANE ",
            /*lastName*/ "DOE  ",
            /*fico*/ 720);
        assertEquals("00000000123", v.accountId());
        assertEquals("Y", v.activeStatus());
        assertEquals(new java.math.BigDecimal("1234.56"), v.currentBalance());
        assertEquals("JANE", v.customerFirstName());   // trailing COBOL spaces trimmed
        assertEquals("DOE", v.customerLastName());
        assertEquals(720, v.ficoScore());
    }
}
