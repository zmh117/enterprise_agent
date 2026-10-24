// Deliberately wrong: every order needs finance approval.
class OrderPolicy {
    static boolean canApprove(int amountCents, boolean finance) {
        return amountCents <= 100000 || finance;
    }
}
