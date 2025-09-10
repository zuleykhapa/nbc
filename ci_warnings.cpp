#include <iostream>
#include <cstdlib>
#include <sstream>
#include <string>

int main() {
    // Example dynamic message
    std::ostringstream oss;
    oss << "Test had failed";

    const char *ci = std::getenv("CI");
    std::string message;

    if (ci && std::string(ci) == "true") {
        // If running in CI, format GitHub Actions notice
        message = "::notice title=Test Failure::" + oss.str();
    } else {
        // Otherwise, just the plain message
        message = oss.str();
    }

    std::cout << message << std::endl;

    // Static warning message for CI
    std::cout << "::warning::This is a warning message in the CI workflow!" << std::endl;

    // Static error message for CI
    std::cerr << "::error::This is an error message in the CI workflow!" << std::endl;

    return 0;
}
