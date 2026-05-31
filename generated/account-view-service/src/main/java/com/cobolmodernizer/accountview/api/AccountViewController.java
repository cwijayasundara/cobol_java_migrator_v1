package com.cobolmodernizer.accountview.api;

import com.cobolmodernizer.accountview.domain.AccountViewService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class AccountViewController {
    private final AccountViewService service;

    public AccountViewController(AccountViewService service) { this.service = service; }

    @GetMapping("/api/accounts/{acctId}/view")
    public ResponseEntity<AccountView> view(@PathVariable String acctId) {
        AccountView v = service.view(acctId);
        return v == null ? ResponseEntity.notFound().build() : ResponseEntity.ok(v);
    }
}
