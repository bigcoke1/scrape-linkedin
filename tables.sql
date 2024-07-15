CREATE TABLE "job_links" (
	"id"	INTEGER UNIQUE,
	"desired_result"	TEXT,
	"organization"	TEXT,
	"link"	TEXT,
	"job_title"	TEXT,
	"date"	TEXT,
	PRIMARY KEY("id")
)