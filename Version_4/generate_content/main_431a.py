def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def multiply(a, b):
    return a * b

def divide(a, b):
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero")
    return a / b

def power(a, b):
    return a ** b

def get_number(prompt: str) -> float:
    while True:
        try:
            return float(input(prompt))
        except ValueError:
            print("Invalid number, please try again.")

def get_operator() -> str:
    ops = {"+": add, "-": subtract, "*": multiply, "/": divide, "^": power}
    while True:
        op = input("Enter operator (+, -, *, /, ^) or 'q' to quit: ").strip()
        if op.lower() == 'q':
            return 'q'
        if op in ops:
            return op
        print("Invalid operator, please try again.")

def main():
    print("Simple Python Calculator")
    while True:
        op = get_operator()
        if op == 'q':
            print("Goodbye!")
            break
        a = get_number("Enter first number: ")
        b = get_number("Enter second number: ")
        try:
            result = {
                '+': add,
                '-': subtract,
                '*': multiply,
                '/': divide,
                '^': power
            }[op](a, b)
            print(f"Result: {result}\n")
        except ZeroDivisionError as e:
            print(e)

if __name__ == "__main__":
    main()
