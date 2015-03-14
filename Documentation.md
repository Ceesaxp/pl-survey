# General Overview #

Survey module has been designed to provide a simple yet elegant way to serve a number of survey types. It is built on top of a stock ActiveState Perl distribution requiring no additional modules. Configuration files are stored in XML using custom XML schema. Survey results are kept as plain-text delimitted files. A number of survey options is available.


# Survey Definition File #

Survey configuration is stored in XML. A separate XML survey definition file is expected for each survey. File name also acts as survey ID that is cross-referenced within the CGI application.

Survey definition file must conform to following structure:

```
<?xml version="1.0" encoding="utf-8"?>
<survey id="sid200801"
        description="Trade Finance Assessment"
        validFrom="20080324"
        validTill="20080430"
        surveyType="Assessment"
        protected="no"
        accessKey="<secret_code_word>"
        verboseResults="yes"
        passRate="16"
        logUsers="yes"
        active="yes">

  <surveyInstructions>
  ...
  </surveyInstructions>

  <question key="1" type="radio" text="Which is not a type of Trade Finance?" answerKey="c">
    <answer key="a">Trade Loans</answer>
    <answer key="b">Receivables Purchase</answer>
    <answer key="c">Collections</answer>
    <answer key="d">Supplier Finance</answer>
  </question>
</survey>
```

You can download compact RelaxNG XML schema for survey definition file for use with your XML editor. DTD and XSD formats are also available.

## Survey Types ##

This application supports a variety of question/answer type surveys, namely:

### Poll ###
Simplest type of a survey, only one question with a set of answers is expected. Typically, a poll is an anonymous survey, but administrator may choose to log source IPs in order to filter multiple submissions from the same host. There are no right or wrong ansers.
### Quiz or Assessment ###
Users are typically logged, questions have assignments of "correct" answers and user results may have to accrue the lowest passing rate. Optionally, a user may be shown what are right and wrong answers and how well he or she scored.
### Questionnaire or Survey ###
Similarly to poll, there are no rights or wrongs, but the number of questions is not limited. Full options to log user activities and user access.

## Survey Attributes ##
### id ###
Survey ID. Must match with file name, i.e. if survey definition is saved as `sid200801.xml`, id attrubute must be set to `sid200801`.
### description ###
Short survey description. A more elaborate decription and survey-taking instructions should be included into `surveyInstructions` tag.
### validFrom, validTill ###
Validity dates for the survey. These are optional parameters, must express validity interval in short ISO date format (i.e. `YYYYMMDD`). If not set, survey will be considered active forever or until active attribute is set to no.
### surveyType ###
This attribute is used primarily for two purposes: as a naming parameter to be used when building forms and results, as well as helping to define survey flow.
### protected ###
Boolean, possible values are (`yes|no`). Restrict access to survey. Requires `accessKey` to be set.
### accessKey ###
Survey access key. Caution: stored in plain text in survey definition file! Must be set if a survey is flagged as protected.
### verboseResults ###
Boolean, possible values are (`yes|no`). If set to 'yes', at the end of the survey user will be given detailed account of his or her answers. If survey is of quiz type, then comparison of rights and wrong will be done, providing optional `answerHint` for the user, explaining why a given answer is right.
### passRate ###
Sets minimal passing rate for a survey as a number of correct answers. Totally irrelevant for polls and plain surveys, only works for quiz.
### logUsers ###
Boolean, possible values are (`yes|no`). If set, then user will have to log in and results file will include his log in details.
### active ###
Boolean, possible values are (`yes|no`). When set to '`no`' will cause a survey to be marked as inactive. Accessing an inactive survey will not record your answers.

## surveyInstructions ##
`surveyInstructions` tag can be used to provide additional information (e.g. instructions) on particular survey usage.

## `question` Attributes ##

### key ###
Question key.

### type ###
Question type. One of (`radio|multi|comment`). If 'comment' is selected, then you can optionally modify the size of text area input by providing rows and cols attributes.

### answerKey ###
Correct answer assignment. relevant only for quiz-type survey. Multiple answers in 'multi' typed question should be separated with commas.

### answerHint ###
Explanation of why a given answer is correct.

### text ###
Question text.

## `answer` Attributes ##
Answer has only one attribute: key.

## Results File ##
Survey results file is a plain-text delimited file with pipe character ("|", ASCII()) is used as a field delimiter. The following sequence of fields is recorded:

```
date_time_stamp|user_id|ip_address|survey_id|q1:a1|q2:a2|...|qN:aN|rights|wrongs
```

A sample results file presented below:

```
2008-03-19 17:45:59|ab12345|127.0.0.1|sid200801|q1:a|q2:a|q3:a|...|6|13
2008-03-19 18:33:13|bc23456|127.0.0.1|sid200801|q1:b|q2:a|q3:b|...|9|10
2008-03-19 18:36:21|de34567|127.0.0.1|sid200801|q1:c|q2:c|q3:a|...|9|10
```

In case of multiple answers to a question (when question type is set to 'multi'), answer keys are separated by `NULL`s (e.g. `q2:a\0x00d\0x00f`). Free-text answers (when question type is set to 'text') are stored in double quotes with new line characters replaced by '\n', tab characters replaced with '\t' and pipe charcters replaced by '\|' escapes:

```
q7:"An\\tanswer with\\ncharacter\\|escapes"
```

## Other Considerations/Caveats ##

There are a few.