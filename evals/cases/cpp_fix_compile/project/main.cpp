#include <iostream>
#include <vector>

int sum_positive(const std::vector<int>& values) {
    int total = 0;
    for (int value : values) {
        if (value > 0) {
            total += values;
        }
    }
    return total;
}

int main() {
    std::vector<int> values{1, -2, 3, 4, -5};
    std::cout << sum_positive(values) << '\n';
    return 0;
}
