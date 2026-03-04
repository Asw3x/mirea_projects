numbers = list(map(float, input("Введите числа через пробел: ").split()))

if not numbers:
    print("Список чисел пуст")
else:
    print(f"Минимум: {min(numbers)}")
    print(f"Максимум: {max(numbers)}")
    print(f"Среднее: {sum(numbers) / len(numbers)}")
