#include <iostream>
#include <cstdlib>
#include <sstream>

int main() {
    // Example notice message for GitHub Actions
    std::ostringstream oss;
    oss << "Test had failed";
    const char *ci = std::getenv("CI");
	// check the value is "true" otherwise you'll see the prefix in local run outputs
	auto prefix = (ci && string(ci) == "true") ? "::notice title=%s::", oss.str() : "";
    std::cout << prefix << std::endl;

    // Example warning message for GitHub Actions
    std::cout << "::warning::This is a warning message in the CI workflow!" << std::endl;

    // Example error message for GitHub Actions
    std::cerr << "::error::This is an error message in the CI workflow!" << std::endl;


    return 0;
}
