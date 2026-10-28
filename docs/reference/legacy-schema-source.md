## Database Schema: `users`

**Description:** Stores user accounts, authentication credentials, personal information, and company associations.

### Table Definition

| Column | Data Type | Nullable | Default | Constraints |
|---|---|---|---|---|
| id | INT UNSIGNED | No | AUTO_INCREMENT | PRIMARY KEY |
| email | VARCHAR(255) | No | — | Composite UNIQUE with company_id |
| password | VARCHAR(60) | No | — | UNIQUE |
| last_login | TIMESTAMP | No | CURRENT_TIMESTAMP | |
| first_name | VARCHAR(255) | Yes | NULL | |
| last_name | VARCHAR(255) | Yes | NULL | |
| created_at | TIMESTAMP | Yes | NULL | Laravel timestamps |
| updated_at | TIMESTAMP | Yes | NULL | Laravel timestamps |
| company_id | INT | Yes | NULL | INDEX |
| employee_id | VARCHAR(10) | Yes | NULL | |
| profile_image | VARCHAR(100) | No | — | |
| middle_name | VARCHAR(50) | No | — | |
| phone_number | VARCHAR(20) | No | — | |

### Indexes and Constraints

| Name | Type | Columns |
|---|---|---|
| PRIMARY | PRIMARY KEY | id |
| users_password_uindex | UNIQUE | password |
| users_email_unique | UNIQUE | email, company_id |
| users_company_id_index | INDEX | company_id |


## Database Schema: `shipments`

**Description:** Stores shipment records, including shipment identifiers, account and company associations, shipping details, sender and recipient references, driver assignments, merchant integrations, and delivery information.

### Table Definition

| Column | Data Type | Nullable | Default | Constraints |
|---|---|---|---|---|
| id | INT UNSIGNED | No | AUTO_INCREMENT | PRIMARY KEY |
| shipment_number | VARCHAR(30) | No | '' | Composite UNIQUE with company_id |
| account_id | VARCHAR(16) | No | — | INDEX |
| company_id | INT | No | — | Composite UNIQUE with shipment_number |
| service_type | VARCHAR(30) | Yes | NULL | |
| order_date | DATE | Yes | NULL | INDEX |
| cost | DECIMAL(10,0) | Yes | NULL | |
| notes | TEXT | Yes | NULL | |
| pod_name | VARCHAR(128) | Yes | NULL | |
| pieces | INT | Yes | NULL | |
| route | VARCHAR(25) | Yes | NULL | |
| weight | DECIMAL(5,0) | Yes | NULL | |
| recipient_id | INT | Yes | NULL | INDEX |
| sender_id | INT | Yes | NULL | |
| shipper_ref | VARCHAR(255) | Yes | NULL | INDEX |
| driver | INT | Yes | NULL | |
| mobile | BOOLEAN / TINYINT(1) | Yes | 0 | |
| merchant_id | INT UNSIGNED | Yes | NULL | |
| integration_type | VARCHAR(20) | Yes | NULL | INDEX |
| vendor_seen | BOOLEAN / TINYINT(1) | Yes | 0 | |
| merchant_seen | BOOLEAN / TINYINT(1) | Yes | 0 | |
| shipper_ref2 | VARCHAR(255) | Yes | NULL | |
| created_at | TIMESTAMP | Yes | NULL | Laravel timestamps |
| updated_at | TIMESTAMP | Yes | NULL | Laravel timestamps |
| deleted_at | TIMESTAMP | Yes | NULL | Soft delete |

### Indexes and Constraints

| Name | Type | Columns |
|---|---|---|
| PRIMARY | PRIMARY KEY | id |
| shipments_shipment_number_company_id_pk | UNIQUE | shipment_number, company_id |
| shipments_account_id_index | INDEX | account_id |
| date | INDEX | order_date |
| shipments_recipient_id_index | INDEX | recipient_id |
| shipments_shipper_ref_index | INDEX | shipper_ref |
| shipments_integration_type_index | INDEX | integration_type |
| account_date | INDEX | account_id, order_date |
| shipments_customer_id_company_id_index | INDEX | customer_id, company_id |

### Relationships

The following are potential application-level relationships inferred from the column names. No foreign key constraints are defined.

- `shipments.company_id` → `companies.id`
- `shipments.recipient_id` → `customers.id`
- `shipments.sender_id` → `customers.id`
- `shipments.merchant_id` → `companies.id`

## Database Schema: `shipment_status`

**Description:** Stores shipment lifecycle timestamps, including shipping, pickup, possession, dispatch, delivery, estimated arrival, and delivery deadlines. Each record can be associated with a shipment.

### Table Definition

| Column | Data Type | Nullable | Default | Constraints |
|---|---|---|---|---|
| id | INT | No | AUTO_INCREMENT | PRIMARY KEY |
| shipment_id | INT UNSIGNED | Yes | NULL | Composite INDEX |
| ship_time | DATETIME | Yes | NULL | |
| pickup_time | DATETIME | Yes | NULL | INDEX |
| possession_time | DATETIME | Yes | NULL | |
| dispatch_time | DATETIME | Yes | NULL | INDEX |
| deliver_time | DATETIME | Yes | NULL | INDEX |
| due_time | DATETIME | Yes | NULL | INDEX |
| created_at | TIMESTAMP | Yes | NULL | Laravel timestamps |
| updated_at | TIMESTAMP | Yes | NULL | Laravel timestamps |
| eta_time | DATETIME | Yes | NULL | |
| due_date | DATE | Yes | NULL | INDEX |

### Indexes and Constraints

| Name | Type | Columns |
|---|---|---|
| PRIMARY | PRIMARY KEY | id |
| shipment_status_pickup_time_index | INDEX | pickup_time |
| shipment_status_dispatch_time_index | INDEX | dispatch_time |
| shipment_status_deliver_time_index | INDEX | deliver_time |
| shipment_status_due_time_index | INDEX | due_time |
| shipment_status_due_date_index | INDEX | due_date |
| times | INDEX | deliver_time, due_time, due_date |
| shipment_status_shipment_id_due_date_index | INDEX | shipment_id, due_date |

### Relationships

- `shipment_status.shipment_id` → `shipments.id`
- The migration does not define a foreign key constraint.
- Each shipment status record may reference one shipment.
- `shipment_id` should be unique but not required, a shipment can only have one shipment_status.


### Implementation Notes

- `shipment_id` is an optional unsigned integer, compatible with the `shipments.id` column.
- All lifecycle timestamps are optional.
- `due_time` stores the delivery deadline as a DATETIME.
- `due_date` separately stores the delivery deadline as a DATE.
- `eta_time` stores the estimated arrival or delivery time.
- `deliver_time` stores the actual delivery timestamp.
- `created_at` and `updated_at` are managed by Laravel's timestamp conventions.
- The composite index `(deliver_time, due_time, due_date)` supports queries starting with `deliver_time` and optionally filtering by the subsequent indexed columns.
- The composite index `(shipment_id, due_date)` supports shipment-specific date queries.

### Business Rules Inferred from Schema

1. A shipment may have associated lifecycle timestamps for shipping, pickup, possession, dispatch, and delivery.
2. All lifecycle timestamp fields can remain NULL until their corresponding events occur.
3. Estimated arrival time (`eta_time`) and actual delivery time (`deliver_time`) are stored independently.
4. Both `due_time` and `due_date` can be used to represent delivery deadlines.

## Database Schema: `shipment_images`

**Description:** Stores shipment-related images, including proof-of-delivery (POD) images, image types, S3 storage locations, and file sizes. Each image record is associated with a shipment.

### Table Definition

| Column | Data Type | Nullable | Default | Constraints |
|---|---|---|---|---|
| id | INT | No | AUTO_INCREMENT | PRIMARY KEY |
| shipment_id | INT UNSIGNED| No | — | INDEX, Composite UNIQUE |
| pod_type | INT | Yes | NULL | Composite UNIQUE |
| created_at | TIMESTAMP | Yes | NULL | Laravel timestamps |
| updated_at | TIMESTAMP | Yes | NULL | Laravel timestamps |
| s3_path | VARCHAR(512) | Yes | NULL | |
| file_size_kb | DECIMAL(10,0) | Yes | NULL | |

### Indexes and Constraints

| Name | Type | Columns |
|---|---|---|
| PRIMARY | PRIMARY KEY | id |
| shipment_pod_shipments_id_fk | INDEX | shipment_id |
| shipment_images__fk | UNIQUE | shipment_id, pod_type |

### Relationships

- `shipment_images.shipment_id` → `shipments.id` (intended relationship).
- One shipment can have multiple image records.
- Each image record belongs to one shipment.

### Implementation Notes

- `shipment_id` is required and indexed.
- `pod_type` is an optional integer representing the image category or proof-of-delivery type.
- `s3_path` stores the image's S3 object path or key, up to 512 characters.
- `file_size_kb` stores the file size as `DECIMAL(10,0)`, without fractional values.
- `created_at` and `updated_at` follow Laravel timestamp conventions.
- The unique constraint `(shipment_id, pod_type)` prevents multiple records with the same non-NULL `pod_type` for one shipment.
- Because `pod_type` is nullable, MySQL permits multiple records with the same `shipment_id` when `pod_type` is NULL.

### Business Rules Inferred from Schema

1. Every shipment image must have a `shipment_id`.
2. A shipment can have multiple images, provided their non-NULL `pod_type` values are different.
3. A shipment cannot have two images with the same non-NULL `pod_type`.
4. Images may be stored in Amazon S3, with their paths recorded in `s3_path`.
5. Image storage paths and file sizes are optional.
6. The meaning and allowed values of `pod_type` are not specified in the migration.

## Database Schema: `customers`

Stores customer information, including company details, address information, and references to validated addresses.

| Column | Data Type | Nullable | Key / Index |
|---|---|---|---|
| id | INT UNSIGNED AUTO_INCREMENT | No | PRIMARY KEY |
| company_id | INT | Yes | INDEX |
| company | VARCHAR(128) | Yes | INDEX |
| address_one | VARCHAR(192) | Yes | INDEX |
| city | VARCHAR(64) | Yes | |
| zip | CHAR(10) | Yes | |
| state | VARCHAR(64) | Yes | |
| validated_id | INT | Yes | INDEX |
| created_at | TIMESTAMP | Yes | |
| updated_at | TIMESTAMP | Yes | |

**Indexes:**
- PRIMARY KEY (`id`)
- INDEX (`company_id`)
- INDEX (`company`)
- INDEX (`address_one`)
- INDEX (`validated_id`)
- COMPOSITE INDEX (`company_id`, `address_one`)

## Database Schema: `customers_validated`

Stores standardized or validated customer address information, including geographic coordinates.

| Column | Data Type | Nullable | Key / Index |
|---|---|---|---|
| id | INT UNSIGNED AUTO_INCREMENT | No | PRIMARY KEY |
| address_one | VARCHAR(192) | Yes | COMPOSITE INDEX |
| address_two | VARCHAR(192) | Yes | COMPOSITE INDEX |
| city | VARCHAR(64) | Yes | COMPOSITE INDEX |
| zip | CHAR(10) | Yes | COMPOSITE INDEX |
| state | VARCHAR(10) | Yes | COMPOSITE INDEX |
| longitude | DECIMAL(11,8) | Yes | |
| latitude | DECIMAL(10,8) | Yes | |
| created_at | TIMESTAMP | Yes | |
| updated_at | TIMESTAMP | Yes | |

**Indexes:**
- PRIMARY KEY (`id`)
- COMPOSITE INDEX (`address_one`, `address_two`, `city`, `state`, `zip`)
  - Index name: `customers_validated_address_one_address_two_city_state_zip_index`

## Table Relationships

| Source Table | Column | Target Table | Target Column | Relationship |
|---|---|---|---|---|
| customers | validated_id | customers_validated | id | Many-to-One (logical) |

**Notes:**
- `customers.validated_id` → `customers_validated.id`.
- Multiple customer records may reference the same validated address.
- The relationship is inferred from the column names. No foreign key constraint is explicitly defined in the provided migrations.
- `customers.company_id` → `company.id`

## Implementation Notes

- Both tables use auto-incrementing unsigned integer primary keys.
- All non-primary-key columns are nullable.
- Geographic coordinates use fixed-point decimals to preserve precision.

## Database Schema:  `company`

Stores company information, including company name, slug, active status, and company type.

| Column | Data Type | Nullable | Key / Index |
|---|---|---|---|
| id | INT AUTO_INCREMENT | No | PRIMARY KEY |
| name | VARCHAR(255) | Yes | |
| slug | VARCHAR(255) | Yes | |
| active | INT | Yes | |
| company_type | INT | No | |

**Indexes:**
- PRIMARY KEY (`company_id`)


**Implementation Notes:**
- `company_id` is an auto-incrementing signed integer primary key.
- `name`, `slug`, and `active` are nullable.
- `company_type` is required (NOT NULL).
- `active` and `company_type` are stored as integers.

