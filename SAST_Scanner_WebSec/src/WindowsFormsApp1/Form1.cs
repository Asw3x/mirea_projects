using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Windows.Forms;
using System.Xml.Linq;
using SecurityLib;

namespace WindowsFormsApp1
{
    public partial class Form1 : Form
    {
        private readonly AnalyzerEngine _analyzer = new AnalyzerEngine();
        private List<BugReport> _findings = new List<BugReport>();

        private TextBox textBoxCode;
        private ListView listViewFindings;
        private Label labelSummary;
        private ComboBox comboBoxFilter;
        private CheckBox checkBoxDeepScan;
        private OpenFileDialog openFileDialog;
        private OpenFileDialog openRulesDialog;

        private ListBox listBoxCustomRules;

        public Form1()
        {
            InitializeComponent();
            BuildUi();
            LoadSampleCode();
        }

        private void BuildUi()
        {
            Text = "SAST Сканер";
            ClientSize = new Size(1200, 800);
            MinimumSize = new Size(900, 600);

            var topPanel = new Panel
            {
                Dock = DockStyle.Top,
                Height = 120,
                Padding = new Padding(8)
            };

            var topLayout = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                ColumnCount = 1,
                RowCount = 2
            };
            topLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 44F));
            topLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));

            var actionPanel = new FlowLayoutPanel
            {
                Dock = DockStyle.Fill,
                FlowDirection = FlowDirection.LeftToRight,
                WrapContents = false,
                AutoScroll = true,
                Padding = new Padding(0),
                Margin = new Padding(0)
            };

            var buttonLoad = new Button
            {
                Text = "Загрузить Файл",
                Width = 90,
                Height = 35,
                Margin = new Padding(0, 8, 8, 8)
            };
            buttonLoad.Click += buttonLoad_Click;

            var buttonAnalyze = new Button
            {
                Text = "Анализ",
                Width = 90,
                Height = 35,
                Margin = new Padding(0, 8, 12, 8)
            };
            buttonAnalyze.Click += buttonAnalyze_Click;

            var buttonLoadRules = new Button
            {
                Text = "Загрузить Паттерны",
                Width = 90,
                Height = 35,
                Margin = new Padding(0, 8, 12, 8)
            };
            buttonLoadRules.Click += buttonLoadRules_Click;

            checkBoxDeepScan = new CheckBox
            {
                Text = "Глубокое Сканирование",
                AutoSize = true,
                Margin = new Padding(0, 13, 12, 8)
            };

            comboBoxFilter = new ComboBox
            {
                DropDownStyle = ComboBoxStyle.DropDownList,
                Width = 140,
                Margin = new Padding(0, 8, 12, 8)
            };
            comboBoxFilter.Items.AddRange(new object[] { "Все", "Critical", "High", "Medium", "Low" });
            comboBoxFilter.SelectedIndex = 0;
            comboBoxFilter.SelectedIndexChanged += comboBoxFilter_SelectedIndexChanged;

            actionPanel.Controls.Add(buttonLoad);
            actionPanel.Controls.Add(buttonAnalyze);
            actionPanel.Controls.Add(buttonLoadRules);
            actionPanel.Controls.Add(checkBoxDeepScan);
            actionPanel.Controls.Add(comboBoxFilter);

            var rulesListPanel = new Panel
            {
                Dock = DockStyle.Fill,
                Padding = new Padding(0, 4, 0, 0)
            };

            listBoxCustomRules = new ListBox
            {
                Dock = DockStyle.Fill,
                IntegralHeight = false
            };

            rulesListPanel.Controls.Add(listBoxCustomRules);

            topLayout.Controls.Add(actionPanel, 0, 0);
            topLayout.Controls.Add(rulesListPanel, 0, 1);
            topPanel.Controls.Add(topLayout);

            var mainLayout = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                ColumnCount = 1,
                RowCount = 2,
                Padding = new Padding(8)
            };
            mainLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
            mainLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 45F));
            mainLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 55F));

            textBoxCode = new TextBox
            {
                Multiline = true,
                ScrollBars = ScrollBars.Both,
                AcceptsTab = true,
                AcceptsReturn = true,
                WordWrap = false,
                Dock = DockStyle.Fill,
                Font = new Font("Consolas", 10F),
                Text = string.Empty
            };
            textBoxCode.TextChanged += textBoxCode_TextChanged;

            labelSummary = new Label
            {
                Dock = DockStyle.Bottom,
                Height = 24,
                Padding = new Padding(8, 0, 8, 0),
                TextAlign = ContentAlignment.MiddleLeft,
                Text = "Готов"
            };

            var codePanel = new Panel { Dock = DockStyle.Fill };
            codePanel.Controls.Add(textBoxCode);
            codePanel.Controls.Add(labelSummary);

            listViewFindings = new ListView
            {
                Dock = DockStyle.Fill,
                View = View.Details,
                FullRowSelect = true,
                GridLines = true,
                HideSelection = false
            };
            listViewFindings.Columns.Add("Правило", 90);
            listViewFindings.Columns.Add("Угроза", 80);
            listViewFindings.Columns.Add("Строка", 60);
            listViewFindings.Columns.Add("Комментарий", 320);
            listViewFindings.Columns.Add("Уязвимый код", 600);

            mainLayout.Controls.Add(codePanel, 0, 0);
            mainLayout.Controls.Add(listViewFindings, 0, 1);

            Controls.Add(mainLayout);
            Controls.Add(topPanel);

            openFileDialog = new OpenFileDialog
            {
                Filter = "Code files|*.cs;*.txt;*.json;*.xml;*.config|All files|*.*",
                Title = "Open source code"
            };

            openRulesDialog = new OpenFileDialog
            {
                Filter = "Rule files|*.xml|All files|*.*",
                Title = "Load SAST rules"
            };
        }

        private void LoadSampleCode()
        {
            textBoxCode.Text = string.Join(Environment.NewLine, new[]
            {
                "var password = \"12345\";",
                "var sql = \"select * from Users where Name = '\" + userName + \"'\";",
                "Process.Start(\"cmd.exe\", \"/c dir\");",
                "var hash = MD5.Create();"
            });
        }

        private void AnalyzeCurrentCode()
        {
            _findings = _analyzer.ScanCode(textBoxCode.Text, checkBoxDeepScan.Checked);
            RenderFindings();
        }

        private void RenderFindings()
        {
            listViewFindings.BeginUpdate();
            listViewFindings.Items.Clear();

            var filteredFindings = _findings
                .Where(ShouldDisplayFinding)
                .OrderByDescending(x => x.Risk)
                .ThenBy(x => x.LineNumber)
                .ToList();

            foreach (var finding in filteredFindings)
            {
                var item = new ListViewItem(finding.RuleId)
                {
                    Tag = finding
                };
                item.SubItems.Add(finding.Severity);
                item.SubItems.Add(finding.LineNumber.ToString());
                item.SubItems.Add(finding.Title);
                item.SubItems.Add(finding.Snippet ?? string.Empty);
                listViewFindings.Items.Add(item);
            }

            listViewFindings.EndUpdate();

            var criticalCount = _findings.Count(x => x.Risk >= 9);
            labelSummary.Text = $"Findings: {_findings.Count} | Critical: {criticalCount} | Showing: {filteredFindings.Count} | Rules: {_analyzer.GetCustomRules().Count}";
        }

        private void RefreshRulesList()
        {
            listBoxCustomRules.Items.Clear();
            foreach (var rule in _analyzer.GetCustomRules())
            {
                listBoxCustomRules.Items.Add($"{rule.RuleId} | {rule.Title} | {rule.Severity} | {rule.Pattern}");
            }
        }

        private bool ShouldDisplayFinding(BugReport finding)
        {
            var filter = comboBoxFilter.SelectedItem?.ToString() ?? "All";

            switch (filter)
            {
                case "Critical":
                    return finding.Risk >= 9;
                case "High":
                    return finding.Risk >= 7;
                case "Medium":
                    return finding.Risk >= 4 && finding.Risk < 7;
                case "Low":
                    return finding.Risk < 4;
                default:
                    return true;
            }
        }

        private void buttonLoad_Click(object sender, EventArgs e)
        {
            if (openFileDialog.ShowDialog(this) != DialogResult.OK)
            {
                return;
            }

            textBoxCode.Text = File.ReadAllText(openFileDialog.FileName);
        }

        private void buttonLoadRules_Click(object sender, EventArgs e)
        {
            if (openRulesDialog.ShowDialog(this) != DialogResult.OK)
            {
                return;
            }

            try
            {
                var added = _analyzer.LoadCustomRulesFromXmlFile(openRulesDialog.FileName);
                RefreshRulesList();
                AnalyzeCurrentCode();
                MessageBox.Show(this, $"Loaded rules: {added}", "Rules import", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, ex.Message, "Rules import failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void buttonAnalyze_Click(object sender, EventArgs e)
        {
            AnalyzeCurrentCode();
        }

        private void comboBoxFilter_SelectedIndexChanged(object sender, EventArgs e)
        {
            RenderFindings();
        }

        private void checkBoxUploadToCloud_CheckedChanged(object sender, EventArgs e)
        {
            // No cloud upload in this local SAST scanner.
        }

        private void radioButtonQuickScan_CheckedChanged(object sender, EventArgs e)
        {
            // No-op.
        }

        private void radioButtonDeepScan_CheckedChanged(object sender, EventArgs e)
        {
            // No-op.
        }

        private void textBoxCode_TextChanged(object sender, EventArgs e)
        {
            labelSummary.Text = $"Code lines: {textBoxCode.Lines.Length}";
        }
    }
}

