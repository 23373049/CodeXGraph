#include <stdio.h>
#include <stdlib.h>

int aqq(int a, int b);
int subtract(int a, int b);

struct aa{
    int a;
    int b;
};


// 普通函数：加法
int aqq(int a, int b) {
    return a + b;
}

// 普通函数：减法
int subtract(int a, int b) {
    return a - b;
}

// 主函数
int main() {

   
    int sum1 = aqq(10, 20);
    int sum2 = subtract(-5, 15);

    return 0;
}