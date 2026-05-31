package com.cobolmodernizer.accountview.api;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup;

import com.cobolmodernizer.accountview.domain.AccountViewService;
import java.math.BigDecimal;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;

// Spring Boot 4 moved @WebMvcTest into a separate test-slice module not pulled by
// starter-test; standaloneSetup tests the controller using only spring-test + mockito.
class AccountViewControllerTest {

    private final AccountViewService service = mock(AccountViewService.class);
    private final MockMvc mvc = standaloneSetup(new AccountViewController(service)).build();

    @Test
    void returnsAccountViewJson() throws Exception {
        when(service.view("00000000123")).thenReturn(
            new AccountView("00000000123", "Y", new BigDecimal("1234.56"),
                new BigDecimal("5000.00"), "000000042", "JANE", "DOE", 720));
        mvc.perform(get("/api/accounts/00000000123/view"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.accountId").value("00000000123"))
           .andExpect(jsonPath("$.currentBalance").value(1234.56))
           .andExpect(jsonPath("$.customerLastName").value("DOE"));
    }

    @Test
    void returns404WhenNotFound() throws Exception {
        when(service.view("99999999999")).thenReturn(null);
        mvc.perform(get("/api/accounts/99999999999/view"))
           .andExpect(status().isNotFound());
    }
}
