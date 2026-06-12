using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace SecurityLib
{
    public class BugReport
    {
        public string RuleId { get; set; }
        public string Title { get; set; }
        public string Severity { get; set; }
        public int Risk { get; set; }
        public int LineNumber { get; set; }
        public string Snippet { get; set; }
    }

    public class ScannerRule
    {
        public string RuleId { get; set; }
        public string Title { get; set; }
        public string Severity { get; set; }
        public int Risk { get; set; }
        public string Pattern { get; set; }
        public bool UseRegex { get; set; }
        public bool CaseInsensitive { get; set; }
        public bool DeepScanOnly { get; set; }
    }

    public class AnalyzerEngine
    {
        private static readonly Regex[] SecretPatterns =
        {
            new Regex(@"(?i)\b(password|pwd|secret|token|apikey|api_key|connectionstring)\b\s*[:=]\s*['""][^'""]+['""]", RegexOptions.Compiled),
            new Regex(@"(?i)\b(password|pwd|secret|token|apikey|api_key|connectionstring)\b\s*[:=]\s*[^\s;]+", RegexOptions.Compiled)
        };

        private readonly List<ScannerRule> _customRules = new List<ScannerRule>();

        public void AddCustomRule(ScannerRule rule)
        {
            if (rule == null)
            {
                return;
            }

            if (string.IsNullOrWhiteSpace(rule.RuleId) || string.IsNullOrWhiteSpace(rule.Pattern) || string.IsNullOrWhiteSpace(rule.Title))
            {
                return;
            }

            _customRules.RemoveAll(x => string.Equals(x.RuleId, rule.RuleId, StringComparison.OrdinalIgnoreCase));
            _customRules.Add(rule);
        }

        public int LoadCustomRulesFromXmlFile(string filePath)
        {
            if (string.IsNullOrWhiteSpace(filePath))
            {
                return 0;
            }

            var document = XDocument.Load(filePath);
            var root = document.Root;
            if (root == null)
            {
                return 0;
            }

            var added = 0;
            foreach (var ruleElement in root.Elements("Rule"))
            {
                var rule = new ScannerRule
                {
                    RuleId = (string)ruleElement.Attribute("id") ?? string.Empty,
                    Title = (string)ruleElement.Attribute("title") ?? string.Empty,
                    Severity = (string)ruleElement.Attribute("severity") ?? "High",
                    Pattern = ruleElement.Element("Pattern")?.Value ?? string.Empty,
                    UseRegex = ParseBool(ruleElement.Attribute("regex")?.Value, true),
                    CaseInsensitive = ParseBool(ruleElement.Attribute("ignoreCase")?.Value, true),
                    DeepScanOnly = ParseBool(ruleElement.Attribute("deepScanOnly")?.Value, false)
                };

                var riskText = (string)ruleElement.Attribute("risk");
                if (!int.TryParse(riskText, out var risk))
                {
                    risk = 7;
                }

                rule.Risk = risk;

                var beforeCount = _customRules.Count;
                AddCustomRule(rule);
                if (_customRules.Count > beforeCount)
                {
                    added++;
                }
            }

            return added;
        }

        public List<ScannerRule> GetCustomRules()
        {
            return new List<ScannerRule>(_customRules);
        }

        public List<BugReport> ScanCode(string sourceCode, bool isDeepScan)
        {
            var reports = new List<BugReport>();

            if (string.IsNullOrWhiteSpace(sourceCode))
            {
                return reports;
            }

            var lines = sourceCode.Replace("\r\n", "\n").Split('\n');

            for (var index = 0; index < lines.Length; index++)
            {
                var line = lines[index];
                var trimmed = line.Trim();
                var lineNumber = index + 1;

                if (IsMatch(SecretPatterns, line))
                {
                    AddFinding(reports, "SAST-001", "Возможная утечка учетных данных", "Critical", 9, lineNumber, trimmed);
                }

                if (ContainsSqlConstruction(trimmed))
                {
                    AddFinding(reports, "SAST-002", "Возможная SQL-инъекция", "High", 8, lineNumber, trimmed);
                }

                if (ContainsCommandExecution(trimmed))
                {
                    AddFinding(reports, "SAST-003", "Потенциальное выполнение команд ОС", "High", 8, lineNumber, trimmed);
                }

                if (isDeepScan && ContainsWeakCrypto(trimmed))
                {
                    AddFinding(reports, "SAST-004", "Слабая криптография или небезопасная сериализация", "Medium", 6, lineNumber, trimmed);
                }

                ApplyCustomRules(reports, trimmed, lineNumber, isDeepScan);
            }

            return reports;
        }

        private static bool ParseBool(string value, bool defaultValue)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return defaultValue;
            }

            if (bool.TryParse(value, out var parsed))
            {
                return parsed;
            }

            return defaultValue;
        }

        private void ApplyCustomRules(List<BugReport> reports, string line, int lineNumber, bool isDeepScan)
        {
            for (var i = 0; i < _customRules.Count; i++)
            {
                var rule = _customRules[i];

                if (rule.DeepScanOnly && !isDeepScan)
                {
                    continue;
                }

                if (MatchesRule(rule, line))
                {
                    AddFinding(reports, rule.RuleId, rule.Title, rule.Severity, rule.Risk, lineNumber, line);
                }
            }
        }

        private static bool MatchesRule(ScannerRule rule, string text)
        {
            if (string.IsNullOrWhiteSpace(rule.Pattern) || string.IsNullOrWhiteSpace(text))
            {
                return false;
            }

            if (rule.UseRegex)
            {
                var options = RegexOptions.Compiled;
                if (rule.CaseInsensitive)
                {
                    options |= RegexOptions.IgnoreCase;
                }

                return Regex.IsMatch(text, rule.Pattern, options);
            }

            if (rule.CaseInsensitive)
            {
                return text.IndexOf(rule.Pattern, StringComparison.OrdinalIgnoreCase) >= 0;
            }

            return text.IndexOf(rule.Pattern, StringComparison.Ordinal) >= 0;
        }

        private static bool IsMatch(IEnumerable<Regex> patterns, string text)
        {
            foreach (var pattern in patterns)
            {
                if (pattern.IsMatch(text))
                {
                    return true;
                }
            }

            return false;
        }

        private static bool ContainsSqlConstruction(string text)
        {
            var normalized = text.ToLowerInvariant();

            return (normalized.Contains("select ") || normalized.Contains("insert ") || normalized.Contains("update ") || normalized.Contains("delete "))
                   && (text.Contains("+") || text.Contains("$\"") || normalized.Contains("string.format(") || normalized.Contains("stringbuilder"));
        }

        private static bool ContainsCommandExecution(string text)
        {
            var normalized = text.ToLowerInvariant();

            return normalized.Contains("process.start(")
                   || normalized.Contains("cmd.exe")
                   || normalized.Contains("powershell")
                   || normalized.Contains("shellexecute = true");
        }

        private static bool ContainsWeakCrypto(string text)
        {
            var normalized = text.ToLowerInvariant();

            return normalized.Contains("md5")
                   || normalized.Contains("sha1")
                   || normalized.Contains("binaryformatter")
                   || normalized.Contains("rijndaelmanaged")
                   || normalized.Contains("descryptoserviceprovider");
        }

        private static void AddFinding(List<BugReport> reports, string ruleId, string title, string severity, int risk, int lineNumber, string snippet)
        {
            reports.Add(new BugReport
            {
                RuleId = ruleId,
                Title = title,
                Severity = severity,
                Risk = risk,
                LineNumber = lineNumber,
                Snippet = snippet
            });
        }
    }
}
