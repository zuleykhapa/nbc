#include <iostream>
#include <cstdlib>

int main() {
    // Example warning message for GitHub Actions
    std::cout << "::warning::This is a warning message in the CI workflow!" << std::endl;

    // Example error message for GitHub Actions
    std::cerr << "::error::This is an error message in the CI workflow!" << std::endl;

    // Example notice message for GitHub Actions
    std::cout << "::notice::This is a notice message in the CI workflow!" << std::endl;

    return 0;
}
