1. How @require_auth distinguishes a missing header, a malformed header, a bad signature and an expired token, and what each returns:

Missing Header: Checks if request.headers.get('Authorization') exists. If not, it aborts with a 401 error.

Malformed Header: Splits the header string. If the resulting list doesn't have exactly two parts or the first part isn't "Bearer", it aborts with 401.

Expired Token: Invokes jwt.decode(). If PyJWT raises jwt.ExpiredSignatureError (which happens because we set the exp claim logic), it catches the error and aborts with a 401.

Bad Signature: If PyJWT raises jwt.InvalidSignatureError or jwt.InvalidTokenError when validating the payload against the server's JWT_SECRET, it catches the exception and aborts with 401.

Return Value: In all cases, the abort sends control to the global HTTPException handler, which returns a 401 Unauthorized JSON payload formatted as {"error": "<description>"} and attaches the required WWW-Authenticate: Bearer response header.

2. Why role travels in the token rather than in a lookup, and what a user whose role is revoked can still do until the token expires:

Embedding the role directly as a claim inside the JWT eliminates the need to perform a database lookup for every incoming request, keeping the API stateless, performant, and horizontally scalable.

However, if a user’s role is revoked, they can still perform any action permitted by their old role until the token reaches its expiration date. This is because the server cryptographically validates the token's existing claims without checking the back-end database to see if their state has changed.

3. What a client holding a token observes when the signing key is replaced:

The client's subsequent API requests will instantly be rejected with a 401 Unauthorized (specifically due to a bad signature error).

Because the token was signed with the old key, the server attempting validation with the new key will fail the cryptographic check. The client will need to send a new POST request to /api/login to authenticate and receive a freshly signed JWT.
