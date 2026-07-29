# Minimal SLK Run

This plan starts with GO-001 as Current and no Active GO. After GO-001 enters
`IMPLEMENTING`, `active_go_id` must equal `GO-001`. GO-002 may become Current only
after GO-001 is `VERIFIED` by a D2 PASS receipt.

After every current Required GO has D2 PASS, Verifier performs D3 and Owner decides
the bounded Run verdict.
