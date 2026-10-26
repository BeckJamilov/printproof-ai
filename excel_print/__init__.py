"""Excel Print Optimizer: turn a selection of an Excel worksheet into a verified, print-ready PDF.

Microsoft Excel (through COM automation) is the spreadsheet engine: it recalculates formulas,
applies the workbook's own formatting and exports the PDF. All decisions — which columns and rows
to print, column widths, page fitting — are made by deterministic Python code, and the exported PDF
is verified with PyMuPDF. The original workbook is never modified: Excel works on a temporary copy
that is never saved.
"""
