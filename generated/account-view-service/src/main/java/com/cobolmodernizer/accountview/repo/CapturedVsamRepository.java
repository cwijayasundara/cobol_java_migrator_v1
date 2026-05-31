package com.cobolmodernizer.accountview.repo;

import java.util.Optional;
import org.springframework.stereotype.Repository;

/** ACL data source. In dark-launch it reads the Phase-0 captured VSAM slices
 *  (ACCTDAT/CXACAIX/CUSTDAT) so the new service sees exactly the bytes COBOL saw.
 *  Production replaces this with a CDC/replica reader — domain code is unchanged. */
@Repository
public class CapturedVsamRepository {
    public Optional<byte[]> readXref(String acctId)    { return Optional.empty(); }
    public Optional<byte[]> readAccount(String acctId) { return Optional.empty(); }
    public Optional<byte[]> readCustomer(String custId){ return Optional.empty(); }
}
