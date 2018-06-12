.. _data:

How is data handled securely?
=============================

There are two types of data on the BVP servers - files (e.g. source code, images) and data in a database (e.g. user
data and time series for energy consumption/generation or weather).

* Files are stored on a EBS volumes on Amazon Web Services. These are shared with other customers of Amazon, but protected from them by Linux's chroot system -- each user can see only the files in their own section of the disk.

* Database data is stored in PostgresDB instances which are not shared with other Amazon customers. They are password-protected.

* In addition, no user passwords are stored in clear text - the BVP platform only stores the hashed passwords (encrypted with the bcrypt hashing algorithm). If an attacker steals these password hashes, they cannot compute the passwords from them in a practical amount of time.

* Finally, The application communicates all data with HTTPS, the Hypertext Transfer Protocol encrypted by Transport Layer Security.


