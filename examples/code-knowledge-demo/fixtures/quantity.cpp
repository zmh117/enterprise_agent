// Deliberately wrong: the maximum quantity is 9999.
bool quantityAllowed(int quantity) {
    return quantity > 0 && quantity <= 100;
}
