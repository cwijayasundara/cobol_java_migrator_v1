package com.cobolmodernizer.accountview.acl;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.math.BigDecimal;
import org.junit.jupiter.api.Test;

class PackedDecimalTest {

    // PIC S9(10)V99 COMP-3: 6 bytes -> 11 digits + sign nibble.
    // {00 00 00 01 23 4C} -> digits 00000001234, sign C (positive), scale 2 -> 12.34
    @Test
    void decodesPositivePackedDecimalWithTwoImpliedDecimals() {
        byte[] packed = {0x00, 0x00, 0x00, 0x01, 0x23, 0x4C};
        assertEquals(new BigDecimal("12.34"), PackedDecimal.decode(packed, 2));
    }

    @Test
    void decodesNegativeSignNibbleD() {
        // {07 6D} -> digits 076, sign D (negative), scale 2 -> -0.76
        byte[] packed = {0x07, 0x6D};
        assertEquals(new BigDecimal("-0.76"), PackedDecimal.decode(packed, 2));
    }

    @Test
    void positiveSignNibbleFIsAlsoPositive() {
        // {12 3F} -> digits 123, sign F (unsigned positive), scale 0 -> 123
        assertEquals(new BigDecimal("123"), PackedDecimal.decode(new byte[]{0x12, 0x3F}, 0));
    }
}
