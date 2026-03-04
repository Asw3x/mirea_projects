def factorial(n):
    if n == 0:
        return 1
    result = 1
    for i in range(1, n + 1):
        result *= i
    return result


n = int(input("Введите натуральное число: "))
if n < 0:
    print("Факториал отрицательного числа не определён")
else:
    print(f"{n}! = {factorial(n)}")
