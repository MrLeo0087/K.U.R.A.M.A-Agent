import sys

def is_prime(n: int) -> bool:
    """Return True if n is a prime number, False otherwise.
    Handles negative numbers and 0,1 as non‑prime.
    """
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True

def classify_number(n: int) -> str:
    return f"{n} is {'a prime' if is_prime(n) else 'not a prime'} number."

def main():
    if len(sys.argv) > 1:
        # Numbers passed as command‑line arguments
        for arg in sys.argv[1:]:
            try:
                num = int(arg)
                print(classify_number(num))
            except ValueError:
                print(f"'{arg}' is not an integer.")
    else:
        # Interactive mode
        try:
            line = input('Enter integers separated by spaces: ')
            for token in line.split():
                num = int(token)
                print(classify_number(num))
        except EOFError:
            pass

if __name__ == "__main__":
    main()
