-- Template for the company's read-only integration surface.
-- The real company runs their own version; VIEWs hide sensitive columns.

DROP VIEW IF EXISTS v_stok;
DROP VIEW IF EXISTS v_karyawan;
DROP VIEW IF EXISTS v_transaksi;
DROP TABLE IF EXISTS stok_barang;
DROP TABLE IF EXISTS karyawan;
DROP TABLE IF EXISTS transaksi;

CREATE TABLE stok_barang (
    id          serial PRIMARY KEY,
    nama        text NOT NULL,
    sku         text NOT NULL,
    qty         integer NOT NULL,
    satuan      text NOT NULL DEFAULT 'pcs',
    gudang      text NOT NULL,
    harga_beli  numeric(12,2)          -- sensitive: excluded from the view
);

CREATE VIEW v_stok AS
    SELECT nama, sku, qty, satuan, gudang FROM stok_barang;

INSERT INTO stok_barang (nama, sku, qty, satuan, gudang, harga_beli) VALUES
 ('Kabel USB Type-C 1m',       'KBL-USBC-1M',  40, 'pcs', 'Gudang A', 12000),
 ('Kabel USB Type-C 2m',       'KBL-USBC-2M',  15, 'pcs', 'Gudang A', 18000),
 ('Kabel HDMI 1.5m',           'KBL-HDMI-15',  22, 'pcs', 'Gudang B', 25000),
 ('Adaptor Charger 20W',       'ADP-20W',       8, 'pcs', 'Gudang A', 45000),
 ('Adaptor Charger 65W',       'ADP-65W',       5, 'pcs', 'Gudang B', 120000),
 ('Mouse Wireless',            'MSE-WL-01',    30, 'pcs', 'Gudang A', 55000),
 ('Keyboard Mekanik',          'KBD-MEC-01',   12, 'pcs', 'Gudang B', 350000),
 ('Flashdisk 64GB',            'FD-64',        70, 'pcs', 'Gudang A', 40000),
 ('Flashdisk 128GB',           'FD-128',       25, 'pcs', 'Gudang A', 75000),
 ('Hardisk Eksternal 1TB',     'HDD-EXT-1T',    9, 'pcs', 'Gudang B', 650000),
 ('Powerbank 10000mAh',        'PB-10K',       18, 'pcs', 'Gudang A', 150000),
 ('Powerbank 20000mAh',        'PB-20K',       11, 'pcs', 'Gudang B', 250000),
 ('Headset Bluetooth',         'HST-BT-01',    14, 'pcs', 'Gudang A', 180000),
 ('Webcam HD 1080p',           'WBC-1080',      7, 'pcs', 'Gudang B', 220000),
 ('Kabel LAN Cat6 5m',         'KBL-LAN-5M',   33, 'pcs', 'Gudang A', 30000);


-- ---------------------------------------------------------------------------
CREATE TABLE karyawan (
    id          serial PRIMARY KEY,
    nama        text NOT NULL,
    nip         text NOT NULL,
    departemen  text NOT NULL,
    jabatan     text NOT NULL,
    status      text NOT NULL DEFAULT 'aktif',   -- aktif | cuti | nonaktif
    gaji        numeric(14,2),                   -- sensitive: not in the view
    nik         text                             -- sensitive: not in the view
);

CREATE VIEW v_karyawan AS
    SELECT nama, nip, departemen, jabatan, status FROM karyawan;

INSERT INTO karyawan (nama, nip, departemen, jabatan, status, gaji, nik) VALUES
 ('Budi Santoso',      'EMP-001', 'Gudang',    'Kepala Gudang',     'aktif',    9000000,  '3201...001'),
 ('Siti Rahayu',       'EMP-002', 'Gudang',    'Staf Gudang',       'aktif',    5000000,  '3201...002'),
 ('Ahmad Fauzi',       'EMP-003', 'Gudang',    'Staf Gudang',       'cuti',     5000000,  '3201...003'),
 ('Dewi Lestari',      'EMP-004', 'Keuangan',  'Manajer Keuangan',  'aktif',    12000000, '3201...004'),
 ('Rizky Pratama',     'EMP-005', 'Keuangan',  'Staf Akunting',     'aktif',    6000000,  '3201...005'),
 ('Putri Anggraini',   'EMP-006', 'Penjualan', 'Manajer Penjualan', 'aktif',    11000000, '3201...006'),
 ('Eko Nugroho',       'EMP-007', 'Penjualan', 'Sales Executive',   'aktif',    7000000,  '3201...007'),
 ('Maya Sari',         'EMP-008', 'Penjualan', 'Sales Executive',   'nonaktif', 7000000,  '3201...008'),
 ('Fajar Hidayat',     'EMP-009', 'IT',        'Sysadmin',          'aktif',    8500000,  '3201...009'),
 ('Nurul Aini',        'EMP-010', 'HRD',       'Staf HRD',          'aktif',    6500000,  '3201...010');


-- ---------------------------------------------------------------------------
CREATE TABLE transaksi (
    id            serial PRIMARY KEY,
    tgl           date NOT NULL,
    no_transaksi  text NOT NULL,
    tipe          text NOT NULL,                 -- masuk | keluar
    nominal       numeric(14,2) NOT NULL,
    keterangan    text,
    dibuat_oleh   text                           -- sensitive: not in the view
);

CREATE VIEW v_transaksi AS
    SELECT tgl, no_transaksi, tipe, nominal, keterangan FROM transaksi;

INSERT INTO transaksi (tgl, no_transaksi, tipe, nominal, keterangan, dibuat_oleh) VALUES
 ('2026-08-01', 'TRX-0001', 'masuk',  15000000, 'Penjualan batch kabel',        'EMP-007'),
 ('2026-08-03', 'TRX-0002', 'keluar',  4500000, 'Pembelian stok adaptor',       'EMP-001'),
 ('2026-08-07', 'TRX-0003', 'masuk',   8200000, 'Penjualan powerbank',          'EMP-007'),
 ('2026-08-10', 'TRX-0004', 'keluar', 12000000, 'Pembelian hardisk & webcam',   'EMP-001'),
 ('2026-08-14', 'TRX-0005', 'masuk',   3300000, 'Penjualan mouse & keyboard',   'EMP-008'),
 ('2026-08-18', 'TRX-0006', 'masuk',  21000000, 'Penjualan borongan flashdisk', 'EMP-006'),
 ('2026-08-22', 'TRX-0007', 'keluar',  1800000, 'Biaya operasional gudang',     'EMP-004'),
 ('2026-08-25', 'TRX-0008', 'masuk',   6700000, 'Penjualan headset',            'EMP-007'),
 ('2026-08-28', 'TRX-0009', 'keluar',  9500000, 'Pembelian stok kabel LAN',     'EMP-001'),
 ('2026-08-31', 'TRX-0010', 'masuk',  14200000, 'Penjualan akhir bulan',        'EMP-006');
