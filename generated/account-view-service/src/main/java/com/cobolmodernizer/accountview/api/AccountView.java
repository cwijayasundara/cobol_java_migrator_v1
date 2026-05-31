package com.cobolmodernizer.accountview.api;

import java.math.BigDecimal;

/** Clean bounded-context DTO — the modernized account-view model, decoupled
 *  from any COBOL copybook layout by the anti-corruption layer. */
public record AccountView(
    String accountId,
    String activeStatus,
    BigDecimal currentBalance,
    BigDecimal creditLimit,
    String customerId,
    String customerFirstName,
    String customerLastName,
    int ficoScore) {}
