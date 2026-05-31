package com.cobolmodernizer.accountview.acl;

import java.math.BigDecimal;
import java.math.BigInteger;

/**
 * Anti-corruption layer primitive: decode IBM COBOL COMP-3 (packed decimal).
 * Each byte holds two 4-bit digits; the final low nibble is the sign
 * (0xC/0xF/0xA/0xE = positive, 0xD/0xB = negative). The COBOL V (implied
 * decimal point) is supplied as {@code scale}. No EBCDIC involved — COMP-3 is
 * numeric nibbles, not characters.
 */
public final class PackedDecimal {
    private PackedDecimal() {}

    public static BigDecimal decode(byte[] bytes, int scale) {
        StringBuilder digits = new StringBuilder();
        int signNibble = bytes[bytes.length - 1] & 0x0F;
        for (int i = 0; i < bytes.length; i++) {
            int b = bytes[i] & 0xFF;
            int hi = (b >> 4) & 0x0F;
            digits.append(hi);
            if (i < bytes.length - 1) {
                int lo = b & 0x0F;
                digits.append(lo);
            }
        }
        BigInteger unscaled = new BigInteger(digits.toString());
        if (signNibble == 0x0D || signNibble == 0x0B) {
            unscaled = unscaled.negate();
        }
        return new BigDecimal(unscaled, scale);
    }
}
