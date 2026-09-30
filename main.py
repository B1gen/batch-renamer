import sys

from batch_rename.app import main, self_test

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--self-test":
        sys.exit(self_test(sys.argv[2]))
    main()
