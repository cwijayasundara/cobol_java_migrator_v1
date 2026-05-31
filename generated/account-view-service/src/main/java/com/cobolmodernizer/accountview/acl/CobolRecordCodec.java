package com.cobolmodernizer.accountview.acl;

import com.cobolmodernizer.accountview.api.AccountView;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;

/** Anti-corruption layer: decode fixed-width COBOL records (CVACT01Y account,
 *  CVACT03Y card-xref, CVCUS01Y customer) into the clean AccountView DTO.
 *  COBOL fixed-width text fields are space-padded; numeric COMP-3 fields go
 *  through {@link PackedDecimal}. */
public final class CobolRecordCodec {
    private CobolRecordCodec() {}

    public static String text(byte[] rec, int offset, int len) {
        return new String(rec, offset, len, StandardCharsets.US_ASCII);
    }

    public static AccountView assemble(
            String acctId, String status, BigDecimal balance, BigDecimal creditLimit,
            String custId, String firstName, String lastName, int fico) {
        return new AccountView(
            acctId.strip(), status,
            balance, creditLimit,
            custId.strip(),
            firstName.strip(), lastName.strip(),
            fico);
    }
}
