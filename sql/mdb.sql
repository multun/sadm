CREATE ROLE mdb WITH LOGIN ENCRYPTED PASSWORD '%%SECRET:mdbdb%%';
CREATE DATABASE mdb OWNER mdb;
