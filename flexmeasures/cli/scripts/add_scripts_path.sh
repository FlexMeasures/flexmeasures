#!/bin/bash

current_dir=$(pwd)

# Declares a function named `save_path` that takes two arguments: `path` and `extension`.
# The function is responsible for checking if the given path is already present in the `bashrc` file.
function save_path() {
    path="$1"
    extension="$2"

    # Check if the path is already present in bashrc
    if grep -qF ". $1" ~/.$2rc; then
        echo "Path already exists in .$2rc"
    else
        # Add the path to bashrc
        echo ". $1" >> ~/.$2rc
        echo "Path added to .$2rc"
    fi
}

# The `main` function is responsible for executing the main logic of the script.
# It sets the `script_path` variable to the path of the "ci" directory under the current directory.
# It sets the `extension` variable to the value passed as an argument to the script.

function find_file() {
  directory="$1"
  extension="$2"
  file=$(find "$directory" -type f -name "click-complete.$extension")
  # Searches for a file with the name "click-complete.<extension>" in the given directory.
  # Assigns the file path to the `file` variable.

  # Check if file was found
  if [[ -n "$file" ]]; then
      echo "$file"
      return 0
  else
      return 1
  fi
}

function main() {
 script_path="$current_dir/flexmeasures/cli/scripts"
 extension="$1"

 if [[ "$extension" != "bash" && "$extension" != "fish" && "$extension" != "zsh" ]]; then
   echo "Invalid extension. Only 'bash', 'fish', or 'zsh' extensions are allowed."
   exit 1
 fi

 # In case file is found, then add the complete path in the required file
 if found_file=$(find_file "$script_path" "$extension"); then
   save_path "$found_file" "$extension"
 else
   echo "No file found with $extension in its name."
   exit 1
 fi
}

# Run the main function with the given extension argument
main "$1"
