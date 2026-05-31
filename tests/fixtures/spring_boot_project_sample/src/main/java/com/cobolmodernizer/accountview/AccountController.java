package com.cobolmodernizer.accountview;

import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/** Minimal slice read endpoint, used by the smoke probe (/api/accounts/{id}). */
@RestController
public class AccountController {

    @GetMapping("/api/accounts/{id}")
    public Map<String, String> getAccount(@PathVariable String id) {
        return Map.of("acctId", id, "balance", "0.00");
    }
}
